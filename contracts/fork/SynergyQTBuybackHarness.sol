// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20QTLike {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

/// @notice Test token with explicit burning.
contract ForkSynQTToken {
    string public constant name = "Synergy QT Fork SYN";
    string public constant symbol = "qtSYN";
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    address public immutable owner;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    error Unauthorized();
    error InsufficientBalance();
    error InsufficientAllowance();

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);

    constructor() {
        owner = msg.sender;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != owner) revert Unauthorized();
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function burn(uint256 amount) external {
        if (balanceOf[msg.sender] < amount) revert InsufficientBalance();
        balanceOf[msg.sender] -= amount;
        totalSupply -= amount;
        emit Transfer(msg.sender, address(0), amount);
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed < amount) revert InsufficientAllowance();
        if (allowed != type(uint256).max) allowance[from][msg.sender] = allowed - amount;
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) private {
        if (balanceOf[from] < amount) revert InsufficientBalance();
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}

/// @notice Externally funded buyback demand. SYN delivered by a solver is
/// burned immediately. The deploying controller may add new demand capacity,
/// but capacity alone is useless unless matching WPOL has also been deposited.
contract L1BuybackBurnEscrowQT {
    ForkSynQTToken public immutable syn;
    IERC20QTLike public immutable wpol;
    uint256 public immutable priceX18;
    address public immutable replenisher;
    uint256 public remainingBase;
    uint256 public totalBurned;

    error Unauthorized();
    error InvalidPrice();
    error DemandExceeded();
    error TransferFailed();

    event BoughtBackAndBurned(
        address indexed solver,
        uint256 baseBurned,
        uint256 quotePaid,
        address indexed receiver
    );
    event DemandCapacityIncreased(uint256 addedBase, uint256 newRemainingBase);

    constructor(
        ForkSynQTToken syn_,
        IERC20QTLike wpol_,
        uint256 priceX18_,
        uint256 maxBase_
    ) {
        if (priceX18_ == 0 || maxBase_ == 0) revert InvalidPrice();
        syn = syn_;
        wpol = wpol_;
        priceX18 = priceX18_;
        replenisher = msg.sender;
        remainingBase = maxBase_;
    }

    function increaseRemainingBase(uint256 amount) external {
        if (msg.sender != replenisher) revert Unauthorized();
        if (amount == 0) revert DemandExceeded();
        remainingBase += amount;
        emit DemandCapacityIncreased(amount, remainingBase);
    }

    function redeem(uint256 baseAmount, address receiver) external returns (uint256 quoteAmount) {
        if (baseAmount == 0 || baseAmount > remainingBase) revert DemandExceeded();
        quoteAmount = baseAmount * priceX18 / 1e18;
        if (quoteAmount == 0 || wpol.balanceOf(address(this)) < quoteAmount) revert DemandExceeded();

        remainingBase -= baseAmount;
        if (!syn.transferFrom(msg.sender, address(this), baseAmount)) revert TransferFailed();
        syn.burn(baseAmount);
        totalBurned += baseAmount;
        if (!wpol.transfer(receiver, quoteAmount)) revert TransferFailed();

        emit BoughtBackAndBurned(msg.sender, baseAmount, quoteAmount, receiver);
    }
}

/// @notice Closed QT auction that sells only protocol inventory already held
/// by this contract. New inventory may be added only by the controller's backed
/// QE refill path; the auction itself can never mint.
contract SynergyQTInventoryAuction {
    uint256 public constant BPS = 10_000;
    uint16 public constant MAX_QT_BPS = 5_000;
    uint16 public constant MAX_DISCOUNT_BPS = 3_000;
    uint64 public constant MIN_REVEAL_BLOCKS = 2;
    uint64 public constant MAX_REVEAL_BLOCKS = 120;

    struct Window {
        uint128 baseAvailable;
        uint128 baseSold;
        uint128 referencePriceX18;
        uint128 auctionPriceX18;
        uint64 expiry;
        uint16 bridgeShareBps;
        bool active;
    }

    struct Commitment {
        bytes32 digest;
        uint64 blockNumber;
    }

    ForkSynQTToken public immutable syn;
    IERC20QTLike public immutable wpol;
    L1BuybackBurnEscrowQT public immutable demand;
    address public immutable governor;
    address public immutable treasury;
    address public immutable bridge;

    uint256 public nextWindowId;
    mapping(uint256 => Window) public windows;
    mapping(address => Commitment) public commitments;
    bool private entered;

    error Unauthorized();
    error InvalidWindow();
    error InvalidCommitment();
    error WindowInactive();
    error InsufficientInventory();
    error TransferFailed();
    error Reentrancy();

    event WindowOpened(
        uint256 indexed id,
        uint256 baseAmount,
        uint256 referencePriceX18,
        uint256 auctionPriceX18,
        uint256 realCapital,
        uint256 inventoryBefore
    );
    event Committed(address indexed solver, bytes32 indexed digest);
    event Filled(uint256 indexed id, address indexed solver, uint256 baseAmount, uint256 payment);

    constructor(
        ForkSynQTToken syn_,
        IERC20QTLike wpol_,
        L1BuybackBurnEscrowQT demand_,
        address governor_,
        address treasury_,
        address bridge_
    ) {
        if (governor_ == address(0) || treasury_ == address(0) || bridge_ == address(0)) {
            revert InvalidWindow();
        }
        syn = syn_;
        wpol = wpol_;
        demand = demand_;
        governor = governor_;
        treasury = treasury_;
        bridge = bridge_;
    }

    modifier nonReentrant() {
        if (entered) revert Reentrancy();
        entered = true;
        _;
        entered = false;
    }

    function openProportionalWindow(
        uint16 qtBps,
        uint16 discountBps,
        uint16 bridgeCoverBps,
        uint16 bridgeShareBps,
        uint256 maxBuybackBase,
        uint64 expiry
    ) external returns (uint256 id, uint256 baseAmount) {
        if (msg.sender != governor) revert Unauthorized();
        if (
            qtBps == 0 || qtBps > MAX_QT_BPS || discountBps > MAX_DISCOUNT_BPS
                || bridgeCoverBps > BPS || bridgeShareBps > BPS || maxBuybackBase == 0
                || expiry <= block.timestamp
        ) revert InvalidWindow();

        uint256 referencePrice = demand.priceX18();
        if (referencePrice == 0) revert InvalidWindow();
        uint256 auctionPrice = referencePrice * (BPS - discountBps) / BPS;
        if (auctionPrice == 0) revert InvalidWindow();

        uint256 realCapital = wpol.balanceOf(treasury) + wpol.balanceOf(bridge);
        uint256 quoteBudget = realCapital * qtBps / BPS;
        uint256 requiredBridge = quoteBudget * bridgeCoverBps / BPS;
        if (quoteBudget == 0 || wpol.balanceOf(bridge) < requiredBridge) revert InvalidWindow();

        baseAmount = quoteBudget * 1e18 / auctionPrice;
        if (baseAmount > maxBuybackBase) baseAmount = maxBuybackBase;
        uint256 inventory = syn.balanceOf(address(this));
        if (baseAmount > inventory) baseAmount = inventory;
        if (baseAmount == 0 || baseAmount > type(uint128).max) revert InsufficientInventory();

        id = nextWindowId++;
        windows[id] = Window({
            baseAvailable: uint128(baseAmount),
            baseSold: 0,
            referencePriceX18: uint128(referencePrice),
            auctionPriceX18: uint128(auctionPrice),
            expiry: expiry,
            bridgeShareBps: bridgeShareBps,
            active: true
        });

        emit WindowOpened(id, baseAmount, referencePrice, auctionPrice, realCapital, inventory);
    }

    function commit(bytes32 digest) external {
        if (digest == bytes32(0) || commitments[msg.sender].digest != bytes32(0)) {
            revert InvalidCommitment();
        }
        commitments[msg.sender] = Commitment(digest, uint64(block.number));
        emit Committed(msg.sender, digest);
    }

    function fill(
        uint256 id,
        uint256 baseAmount,
        uint256 maxPayment,
        bytes32 salt,
        uint64 deadline
    ) external nonReentrant returns (uint256 payment) {
        Window storage w = windows[id];
        if (!w.active || block.timestamp > w.expiry || block.timestamp > deadline) {
            revert WindowInactive();
        }
        if (baseAmount == 0 || uint256(w.baseSold) + baseAmount > w.baseAvailable) {
            revert InsufficientInventory();
        }

        Commitment memory c = commitments[msg.sender];
        bytes32 expected = keccak256(abi.encode(msg.sender, id, baseAmount, maxPayment, salt, deadline));
        if (
            c.digest != expected || block.number < c.blockNumber + MIN_REVEAL_BLOCKS
                || block.number > c.blockNumber + MAX_REVEAL_BLOCKS
        ) revert InvalidCommitment();
        delete commitments[msg.sender];

        uint256 referencePrice = demand.priceX18();
        if (referencePrice == 0 || referencePrice != w.referencePriceX18) revert InvalidWindow();
        payment = baseAmount * uint256(w.auctionPriceX18) / 1e18;
        if (payment == 0 || payment > maxPayment) revert InvalidWindow();

        w.baseSold += uint128(baseAmount);
        if (w.baseSold == w.baseAvailable) w.active = false;

        if (!wpol.transferFrom(msg.sender, address(this), payment)) revert TransferFailed();
        uint256 bridgePart = payment * w.bridgeShareBps / BPS;
        if (bridgePart > 0 && !wpol.transfer(bridge, bridgePart)) revert TransferFailed();
        if (!wpol.transfer(treasury, payment - bridgePart)) revert TransferFailed();
        if (!syn.transfer(msg.sender, baseAmount)) revert TransferFailed();

        emit Filled(id, msg.sender, baseAmount, payment);
    }
}
