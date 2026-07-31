// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import "./SynergyQTBuybackHarness.sol";

/// @notice V2 on-chain model for renewable QE/QT inventory.
///
/// Economic invariants:
/// - the initial 100 SYN are finite: 72 protocol inventory + 28 external holder;
/// - external SYN can be burned only after the holder grants ERC-20 approval;
/// - every refill SYN entering circulation is purchased for 1 WPOL first;
/// - QT tenders buy SYN back for 0.75 WPOL, pay bounded operating costs,
///   and burn the acquired SYN in the same transaction;
/// - there is no cumulative issuance cap, but there is also no unbacked mint path;
/// - dividends are possible only at zero outstanding SYN and preserve a WPOL floor.
contract BackedQETenderQTControllerV2 {
    uint256 public constant BPS = 10_000;
    uint256 public constant PAR_PRICE_X18 = 1e18;
    uint256 public constant INITIAL_SUPPLY = 100e18;
    uint256 public constant INITIAL_PROTOCOL_INVENTORY = 72e18;
    uint256 public constant INITIAL_EXTERNAL_SUPPLY = 28e18;
    uint256 public constant INITIAL_PROTOCOL_WPOL = 43e18;

    uint256 public constant QT_PRICE_X18 = 750_000_000_000_000_000; // 0.75 WPOL/SYN
    uint256 public constant KEEPER_REWARD_X18 = 190_000_000_000_000_000; // 0.19 WPOL/SYN
    uint256 public constant SETTLEMENT_FEE_X18 = 375_000_000_000_000; // 0.000375 WPOL/SYN
    uint256 public constant MIN_OPERATIONAL_RESERVE = 1e18;

    IERC20QTLike public immutable wpol;
    ForkSynQTToken public immutable syn;
    address public immutable dividendRecipient;
    address public immutable settlementFeeRecipient;

    address public bootstrapper;
    bool public bootstrapped;
    bool public initialRecoveryComplete;

    uint256 public totalProtocolInventoryBurned;
    uint256 public totalExternalTenderBurned;
    uint256 public totalQEMinted;
    uint256 public totalRefillQTburned;
    uint256 public totalKeeperRewards;
    uint256 public totalSettlementFees;
    uint256 public totalDividends;
    uint256 public completedOperations;

    error Unauthorized();
    error AlreadyBootstrapped();
    error NotBootstrapped();
    error InvalidConfiguration();
    error InvalidAmount();
    error TransferFailed();
    error InsufficientProtocolInventory();
    error InsufficientReserve();
    error OutstandingLiabilities();

    event Bootstrapped(address indexed externalHolder, uint256 assets, uint256 supply);
    event ProtocolInventoryBurned(uint256 amount, address indexed keeper, uint256 assets, uint256 supply);
    event ExternalTenderBurned(
        address indexed seller,
        uint256 amount,
        uint256 sellerPayment,
        address indexed keeper,
        uint256 assets,
        uint256 supply
    );
    event BackedQEIssued(address indexed buyer, uint256 amount, uint256 payment, uint256 assets, uint256 supply);
    event RefillQTBurned(
        address indexed seller,
        uint256 amount,
        uint256 sellerPayment,
        address indexed keeper,
        uint256 assets,
        uint256 supply
    );
    event InitialRecoveryCompleted(uint256 assets, uint256 totalBurned);
    event DividendPaid(address indexed recipient, uint256 amount, uint256 reserveAfter);

    constructor(
        IERC20QTLike wpol_,
        address dividendRecipient_,
        address settlementFeeRecipient_
    ) {
        if (
            address(wpol_) == address(0) || dividendRecipient_ == address(0)
                || settlementFeeRecipient_ == address(0)
        ) revert InvalidConfiguration();

        wpol = wpol_;
        dividendRecipient = dividendRecipient_;
        settlementFeeRecipient = settlementFeeRecipient_;
        bootstrapper = msg.sender;
        syn = new ForkSynQTToken();
    }

    function bootstrap(address externalHolder) external {
        if (msg.sender != bootstrapper) revert Unauthorized();
        if (bootstrapped) revert AlreadyBootstrapped();
        if (externalHolder == address(0)) revert InvalidConfiguration();

        if (!wpol.transferFrom(msg.sender, address(this), INITIAL_PROTOCOL_WPOL)) revert TransferFailed();
        syn.mint(address(this), INITIAL_PROTOCOL_INVENTORY);
        syn.mint(externalHolder, INITIAL_EXTERNAL_SUPPLY);

        bootstrapped = true;
        bootstrapper = address(0);
        emit Bootstrapped(externalHolder, reserveWPOL(), syn.totalSupply());
    }

    function reserveWPOL() public view returns (uint256) {
        return wpol.balanceOf(address(this));
    }

    function liabilitiesAtPar() public view returns (uint256) {
        return syn.totalSupply() * PAR_PRICE_X18 / 1e18;
    }

    function equityAtPar() public view returns (int256) {
        return int256(reserveWPOL()) - int256(liabilitiesAtPar());
    }

    function totalCostFor(uint256 amount) public pure returns (uint256) {
        return amount * (QT_PRICE_X18 + KEEPER_REWARD_X18 + SETTLEMENT_FEE_X18) / 1e18;
    }

    /// @notice Burns protocol-owned inventory. This recreates the validated
    /// recovery leakage: 0.38 WPOL keeper reward + 0.00075 WPOL fee per 2 SYN.
    function burnProtocolInventory(uint256 amount) external {
        _requireBootstrapped();
        if (amount == 0) revert InvalidAmount();
        if (syn.balanceOf(address(this)) < amount) revert InsufficientProtocolInventory();

        uint256 keeperReward = amount * KEEPER_REWARD_X18 / 1e18;
        uint256 fee = amount * SETTLEMENT_FEE_X18 / 1e18;
        if (reserveWPOL() < keeperReward + fee + MIN_OPERATIONAL_RESERVE) revert InsufficientReserve();

        syn.burn(amount);
        _pay(msg.sender, keeperReward);
        _pay(settlementFeeRecipient, fee);

        totalProtocolInventoryBurned += amount;
        totalKeeperRewards += keeperReward;
        totalSettlementFees += fee;
        completedOperations += 1;
        emit ProtocolInventoryBurned(amount, msg.sender, reserveWPOL(), syn.totalSupply());
        _markInitialRecoveryIfComplete();
    }

    /// @notice Permissionless tender of external SYN. The seller must first
    /// approve this controller. No token can be seized without ERC-20 consent.
    function tenderExternalAndBurn(address seller, uint256 amount) external {
        _requireBootstrapped();
        if (seller == address(0) || amount == 0) revert InvalidAmount();

        uint256 sellerPayment = amount * QT_PRICE_X18 / 1e18;
        uint256 keeperReward = amount * KEEPER_REWARD_X18 / 1e18;
        uint256 fee = amount * SETTLEMENT_FEE_X18 / 1e18;
        if (reserveWPOL() < sellerPayment + keeperReward + fee + MIN_OPERATIONAL_RESERVE) {
            revert InsufficientReserve();
        }

        if (!syn.transferFrom(seller, address(this), amount)) revert TransferFailed();
        syn.burn(amount);
        _pay(seller, sellerPayment);
        _pay(msg.sender, keeperReward);
        _pay(settlementFeeRecipient, fee);

        totalExternalTenderBurned += amount;
        totalKeeperRewards += keeperReward;
        totalSettlementFees += fee;
        completedOperations += 1;
        emit ExternalTenderBurned(
            seller,
            amount,
            sellerPayment,
            msg.sender,
            reserveWPOL(),
            syn.totalSupply()
        );
        _markInitialRecoveryIfComplete();
    }

    /// @notice Unlimited cumulative QE refill with a strict 1 WPOL/SYN cash-in
    /// condition. There is no function that mints without successful payment.
    function buyBackedSYN(uint256 amount) external {
        _requireBootstrapped();
        if (amount == 0) revert InvalidAmount();
        uint256 payment = amount * PAR_PRICE_X18 / 1e18;
        if (!wpol.transferFrom(msg.sender, address(this), payment)) revert TransferFailed();
        syn.mint(msg.sender, amount);
        totalQEMinted += amount;
        completedOperations += 1;
        emit BackedQEIssued(msg.sender, amount, payment, reserveWPOL(), syn.totalSupply());
    }

    /// @notice Burns SYN created by the refill path. The seller must approve
    /// this contract; the caller may be any permissionless keeper.
    function tenderRefillAndBurn(address seller, uint256 amount) external {
        _requireBootstrapped();
        if (seller == address(0) || amount == 0) revert InvalidAmount();

        uint256 sellerPayment = amount * QT_PRICE_X18 / 1e18;
        uint256 keeperReward = amount * KEEPER_REWARD_X18 / 1e18;
        uint256 fee = amount * SETTLEMENT_FEE_X18 / 1e18;
        if (reserveWPOL() < sellerPayment + keeperReward + fee + MIN_OPERATIONAL_RESERVE) {
            revert InsufficientReserve();
        }

        if (!syn.transferFrom(seller, address(this), amount)) revert TransferFailed();
        syn.burn(amount);
        _pay(seller, sellerPayment);
        _pay(msg.sender, keeperReward);
        _pay(settlementFeeRecipient, fee);

        totalRefillQTburned += amount;
        totalKeeperRewards += keeperReward;
        totalSettlementFees += fee;
        completedOperations += 1;
        emit RefillQTBurned(
            seller,
            amount,
            sellerPayment,
            msg.sender,
            reserveWPOL(),
            syn.totalSupply()
        );
    }

    /// @notice Pays only zero-liability surplus and leaves one WPOL available
    /// so a new fully paid refill/tender cycle can start after the dividend.
    function payExcessDividend() external returns (uint256 dividend) {
        _requireBootstrapped();
        if (syn.totalSupply() != 0) revert OutstandingLiabilities();
        uint256 assets = reserveWPOL();
        if (assets <= MIN_OPERATIONAL_RESERVE) return 0;
        dividend = assets - MIN_OPERATIONAL_RESERVE;
        _pay(dividendRecipient, dividend);
        totalDividends += dividend;
        completedOperations += 1;
        emit DividendPaid(dividendRecipient, dividend, reserveWPOL());
    }

    function _markInitialRecoveryIfComplete() private {
        if (!initialRecoveryComplete && syn.totalSupply() == 0) {
            initialRecoveryComplete = true;
            emit InitialRecoveryCompleted(reserveWPOL(), totalProtocolInventoryBurned + totalExternalTenderBurned);
        }
    }

    function _pay(address to, uint256 amount) private {
        if (amount > 0 && !wpol.transfer(to, amount)) revert TransferFailed();
    }

    function _requireBootstrapped() private view {
        if (!bootstrapped) revert NotBootstrapped();
    }
}
