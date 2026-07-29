// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20Like {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IWPOL is IERC20Like {
    function deposit() external payable;
    function withdraw(uint256 amount) external;
}

interface IQuickSwapV2Factory {
    function createPair(address tokenA, address tokenB) external returns (address pair);
    function getPair(address tokenA, address tokenB) external view returns (address pair);
}

interface IQuickSwapV2Pair {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast);
    function mint(address to) external returns (uint256 liquidity);
    function swap(uint256 amount0Out, uint256 amount1Out, address to, bytes calldata data) external;
}

interface IAavePool {
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

contract ForkSynToken {
    string public constant name = "Synergy QE Fork SYN";
    string public constant symbol = "fSYN";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;
    address public immutable owner;
    address public minter;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    error Unauthorized();
    error InsufficientBalance();
    error InsufficientAllowance();

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);

    constructor() { owner = msg.sender; }

    function setMinter(address minter_) external {
        if (msg.sender != owner) revert Unauthorized();
        minter = minter_;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != owner && msg.sender != minter) revert Unauthorized();
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
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

/// @notice Represents externally funded L1 demand. It never mints WPOL: buyers
/// must fund the escrow before a solver can redeem SYN.
contract L1DemandEscrow {
    ForkSynToken public immutable syn;
    IERC20Like public immutable wpol;
    uint256 public immutable priceX18;
    uint256 public remainingBase;

    error InvalidPrice();
    error DemandExceeded();
    error TransferFailed();

    constructor(ForkSynToken syn_, IERC20Like wpol_, uint256 priceX18_, uint256 maxBase_) {
        if (priceX18_ == 0 || maxBase_ == 0) revert InvalidPrice();
        syn = syn_;
        wpol = wpol_;
        priceX18 = priceX18_;
        remainingBase = maxBase_;
    }

    function redeem(uint256 baseAmount, address receiver) external returns (uint256 quoteAmount) {
        if (baseAmount == 0 || baseAmount > remainingBase) revert DemandExceeded();
        quoteAmount = baseAmount * priceX18 / 1e18;
        if (quoteAmount == 0 || wpol.balanceOf(address(this)) < quoteAmount) revert DemandExceeded();
        remainingBase -= baseAmount;
        if (!syn.transferFrom(msg.sender, address(this), baseAmount)) revert TransferFailed();
        if (!wpol.transfer(receiver, quoteAmount)) revert TransferFailed();
    }
}

/// @notice Exclusive QE inventory auction. QE scales only with actual WPOL held
/// by treasury and bridge; inventory is not exposed in a public AMM.
contract SynergyQEVaultAuction {
    uint256 public constant BPS = 10_000;
    uint16 public constant MAX_QE_BPS = 5_000;
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

    ForkSynToken public immutable syn;
    IERC20Like public immutable wpol;
    L1DemandEscrow public immutable demand;
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
        uint256 requiredBridge
    );
    event Committed(address indexed solver, bytes32 indexed digest);
    event Filled(uint256 indexed id, address indexed solver, uint256 baseAmount, uint256 payment);

    constructor(
        ForkSynToken syn_,
        IERC20Like wpol_,
        L1DemandEscrow demand_,
        address governor_,
        address treasury_,
        address bridge_
    ) {
        if (governor_ == address(0) || treasury_ == address(0) || bridge_ == address(0)) revert InvalidWindow();
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
        uint16 qeBps,
        uint16 discountBps,
        uint16 bridgeCoverBps,
        uint16 bridgeShareBps,
        uint256 maxDemandBase,
        uint64 expiry
    ) external returns (uint256 id, uint256 baseAmount) {
        if (msg.sender != governor) revert Unauthorized();
        if (
            qeBps == 0 || qeBps > MAX_QE_BPS || discountBps > MAX_DISCOUNT_BPS
                || bridgeCoverBps > BPS || bridgeShareBps > BPS || maxDemandBase == 0
                || expiry <= block.timestamp
        ) revert InvalidWindow();

        uint256 reference = demand.priceX18();
        if (reference == 0) revert InvalidWindow();
        uint256 auctionPrice = reference * (BPS - discountBps) / BPS;
        if (auctionPrice == 0) revert InvalidWindow();

        uint256 realCapital = wpol.balanceOf(treasury) + wpol.balanceOf(bridge);
        uint256 quoteBudget = realCapital * qeBps / BPS;
        uint256 requiredBridge = quoteBudget * bridgeCoverBps / BPS;
        if (quoteBudget == 0 || wpol.balanceOf(bridge) < requiredBridge) revert InvalidWindow();
        baseAmount = quoteBudget * 1e18 / auctionPrice;
        if (baseAmount > maxDemandBase) baseAmount = maxDemandBase;
        if (baseAmount == 0 || baseAmount > type(uint128).max) revert InvalidWindow();

        id = nextWindowId++;
        windows[id] = Window({
            baseAvailable: uint128(baseAmount),
            baseSold: 0,
            referencePriceX18: uint128(reference),
            auctionPriceX18: uint128(auctionPrice),
            expiry: expiry,
            bridgeShareBps: bridgeShareBps,
            active: true
        });
        syn.mint(address(this), baseAmount);
        emit WindowOpened(id, baseAmount, reference, auctionPrice, realCapital, requiredBridge);
    }

    function commit(bytes32 digest) external {
        if (digest == bytes32(0) || commitments[msg.sender].digest != bytes32(0)) revert InvalidCommitment();
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
        if (!w.active || block.timestamp > w.expiry || block.timestamp > deadline) revert WindowInactive();
        if (baseAmount == 0 || uint256(w.baseSold) + baseAmount > w.baseAvailable) revert InsufficientInventory();

        Commitment memory c = commitments[msg.sender];
        bytes32 expected = keccak256(abi.encode(msg.sender, id, baseAmount, maxPayment, salt, deadline));
        if (
            c.digest != expected || block.number < c.blockNumber + MIN_REVEAL_BLOCKS
                || block.number > c.blockNumber + MAX_REVEAL_BLOCKS
        ) revert InvalidCommitment();
        delete commitments[msg.sender];

        uint256 reference = demand.priceX18();
        if (reference == 0 || reference != w.referencePriceX18) revert InvalidWindow();
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

contract AaveFlashQESolver {
    IAavePool public immutable pool;
    address public immutable operator;
    IERC20Like public immutable wpol;
    ForkSynToken public immutable syn;
    L1DemandEscrow public immutable demand;
    SynergyQEVaultAuction public immutable auction;

    error Unauthorized();
    error Unprofitable();
    error TransferFailed();

    constructor(
        IAavePool pool_,
        IERC20Like wpol_,
        ForkSynToken syn_,
        L1DemandEscrow demand_,
        SynergyQEVaultAuction auction_
    ) {
        operator = msg.sender;
        pool = pool_;
        wpol = wpol_;
        syn = syn_;
        demand = demand_;
        auction = auction_;
    }

    modifier onlyOperator() {
        if (msg.sender != operator) revert Unauthorized();
        _;
    }

    function commitClosed(bytes32 digest) external onlyOperator { auction.commit(digest); }

    function runClosed(
        uint256 borrowAmount,
        uint256 windowId,
        uint256 baseAmount,
        uint256 maxPayment,
        bytes32 salt,
        uint64 deadline,
        uint256 minProfit
    ) external onlyOperator {
        bytes memory params = abi.encode(uint8(1), windowId, baseAmount, maxPayment, salt, deadline, minProfit, address(0));
        pool.flashLoanSimple(address(this), address(wpol), borrowAmount, params, 0);
    }

    function runOpen(uint256 borrowAmount, address pair, uint256 minProfit) external onlyOperator {
        bytes memory params = abi.encode(uint8(2), uint256(0), uint256(0), uint256(0), bytes32(0), uint64(0), minProfit, pair);
        pool.flashLoanSimple(address(this), address(wpol), borrowAmount, params, 0);
    }

    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external returns (bool) {
        if (msg.sender != address(pool) || initiator != address(this) || asset != address(wpol)) revert Unauthorized();
        (uint8 mode, uint256 windowId, uint256 baseAmount, uint256 maxPayment, bytes32 salt, uint64 deadline, uint256 minProfit, address pair) =
            abi.decode(params, (uint8, uint256, uint256, uint256, bytes32, uint64, uint256, address));

        uint256 beforeBalance = wpol.balanceOf(address(this));
        if (mode == 1) {
            if (!wpol.approve(address(auction), maxPayment)) revert TransferFailed();
            auction.fill(windowId, baseAmount, maxPayment, salt, deadline);
            if (!syn.approve(address(demand), baseAmount)) revert TransferFailed();
            demand.redeem(baseAmount, address(this));
        } else if (mode == 2) {
            _buyFromPairAndRedeem(pair, amount);
        } else {
            revert Unauthorized();
        }

        uint256 owing = amount + premium;
        uint256 afterBalance = wpol.balanceOf(address(this));
        if (beforeBalance < amount) revert Unprofitable();
        uint256 preexisting = beforeBalance - amount;
        if (afterBalance < owing + preexisting + minProfit) revert Unprofitable();
        if (!wpol.approve(address(pool), owing)) revert TransferFailed();
        return true;
    }

    function _buyFromPairAndRedeem(address pairAddress, uint256 amountIn) private {
        IQuickSwapV2Pair pair = IQuickSwapV2Pair(pairAddress);
        address t0 = pair.token0();
        address t1 = pair.token1();
        if (!((t0 == address(wpol) && t1 == address(syn)) || (t1 == address(wpol) && t0 == address(syn)))) {
            revert Unauthorized();
        }
        (uint112 r0, uint112 r1,) = pair.getReserves();
        uint256 reserveIn = t0 == address(wpol) ? r0 : r1;
        uint256 reserveOut = t0 == address(syn) ? r0 : r1;
        uint256 amountInWithFee = amountIn * 997;
        uint256 synOut = amountInWithFee * reserveOut / (reserveIn * 1000 + amountInWithFee);
        if (synOut == 0 || !wpol.transfer(pairAddress, amountIn)) revert TransferFailed();
        if (t0 == address(syn)) pair.swap(synOut, 0, address(this), "");
        else pair.swap(0, synOut, address(this), "");
        if (!syn.approve(address(demand), synOut)) revert TransferFailed();
        demand.redeem(synOut, address(this));
    }
}
