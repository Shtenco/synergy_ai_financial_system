// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

/// @notice On-chain execution permission registry.
/// The contract enforces an attested registration/tax-compliance status; it does
/// not itself determine tax residency, tax rates or legal liability.
contract ParticipantTaxRegistry {
    struct Status {
        bool registered;
        uint64 taxCompliantUntil;
        bytes32 taxIdentityHash;
    }

    address public admin;
    mapping(address => bool) public attester;
    mapping(address => Status) private _status;

    error Unauthorized();
    error InvalidAddress();
    error InvalidExpiry();

    event AttesterSet(address indexed account, bool enabled);
    event ParticipantStatusSet(
        address indexed participant,
        bool registered,
        uint64 taxCompliantUntil,
        bytes32 indexed taxIdentityHash
    );

    constructor(address admin_) {
        if (admin_ == address(0)) revert InvalidAddress();
        admin = admin_;
        attester[admin_] = true;
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyAttester() {
        if (!attester[msg.sender]) revert Unauthorized();
        _;
    }

    function setAttester(address account, bool enabled) external onlyAdmin {
        if (account == address(0)) revert InvalidAddress();
        attester[account] = enabled;
        emit AttesterSet(account, enabled);
    }

    function transferAdmin(address nextAdmin) external onlyAdmin {
        if (nextAdmin == address(0)) revert InvalidAddress();
        admin = nextAdmin;
    }

    function setParticipant(
        address participant,
        bool registered,
        uint64 taxCompliantUntil,
        bytes32 taxIdentityHash
    ) external onlyAttester {
        if (participant == address(0)) revert InvalidAddress();
        if (registered && taxCompliantUntil <= block.timestamp) revert InvalidExpiry();
        _status[participant] = Status({
            registered: registered,
            taxCompliantUntil: taxCompliantUntil,
            taxIdentityHash: taxIdentityHash
        });
        emit ParticipantStatusSet(
            participant,
            registered,
            taxCompliantUntil,
            taxIdentityHash
        );
    }

    function status(address participant) external view returns (Status memory) {
        return _status[participant];
    }

    function isEligible(address participant) public view returns (bool) {
        Status memory s = _status[participant];
        return s.registered && s.taxCompliantUntil >= block.timestamp;
    }
}

interface IParticipantTaxRegistryV5 {
    function isEligible(address participant) external view returns (bool);
}

interface ISystemBoundaryV5 {
    function isSystemAddress(address account) external view returns (bool);
}

interface IRealLiquidityRiskGateV5 {
    function latestPass() external view returns (bool);
    function latestInvariantWad() external view returns (uint256);
}

interface IProfitReinvestmentEngineV5 {
    function reinvestProfitFor(address beneficiary, uint256 amountPol)
        external
        returns (uint256 polUsed);

    function depositRetainedProfit(uint256 amountPol)
        external
        returns (uint256 polUsed);
}

/// @notice Settles only actual external reserve-asset profit.
/// Ten percent is declared as a dividend pool, split equally between owner and
/// the keeper-user. Withholding is moved to a tax escrow and every net dividend
/// is automatically reinvested as risk equity. No cash payout exists.
contract AutoReinvestDividendControllerV5 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant DIVIDEND_POOL_BPS = 1_000;
    uint256 public constant OWNER_SHARE_OF_DIVIDEND_BPS = 5_000;
    uint256 public constant WAD = 1e18;

    IERC20 public immutable reserveAsset;
    IParticipantTaxRegistryV5 public immutable registry;
    ISystemBoundaryV5 public immutable boundary;
    IRealLiquidityRiskGateV5 public immutable riskGate;
    IProfitReinvestmentEngineV5 public immutable engine;

    address public immutable ownerBeneficiary;
    address public immutable protocolTreasury;
    address public immutable taxEscrow;
    address public admin;
    uint256 public withholdingBps;
    uint256 public minimumInvariantWad;

    mapping(address => bool) public operator;
    mapping(bytes32 => bool) public sourceUsed;

    uint256 public cumulativeGrossExternalProfit;
    uint256 public cumulativeRetainedReinvestment;
    uint256 public cumulativeGrossDividends;
    uint256 public cumulativeOwnerNetReinvestment;
    uint256 public cumulativeKeeperNetReinvestment;
    uint256 public cumulativeTaxWithheld;

    error Unauthorized();
    error InvalidAddress();
    error InvalidAmount();
    error InvalidPolicy();
    error SourceAlreadyUsed();
    error SystemPayerForbidden();
    error ParticipantNotEligible();
    error RiskInvariantNotMet();
    error BalanceDeltaMismatch();

    event OperatorSet(address indexed account, bool enabled);
    event PolicySet(uint256 withholdingBps, uint256 minimumInvariantWad);
    event ExternalProfitCompounded(
        bytes32 indexed sourceId,
        address indexed externalPayer,
        address indexed keeperUser,
        uint256 grossProfit,
        uint256 retainedReinvestment,
        uint256 ownerGrossDividend,
        uint256 keeperGrossDividend,
        uint256 ownerNetReinvestment,
        uint256 keeperNetReinvestment,
        uint256 taxWithheld
    );

    constructor(
        address reserveAsset_,
        address registry_,
        address boundary_,
        address riskGate_,
        address engine_,
        address ownerBeneficiary_,
        address protocolTreasury_,
        address taxEscrow_,
        uint256 withholdingBps_,
        uint256 minimumInvariantWad_
    ) {
        if (
            reserveAsset_ == address(0) ||
            registry_ == address(0) ||
            boundary_ == address(0) ||
            riskGate_ == address(0) ||
            engine_ == address(0) ||
            ownerBeneficiary_ == address(0) ||
            protocolTreasury_ == address(0) ||
            taxEscrow_ == address(0)
        ) revert InvalidAddress();
        if (withholdingBps_ > 5_000 || minimumInvariantWad_ < WAD) {
            revert InvalidPolicy();
        }

        admin = msg.sender;
        reserveAsset = IERC20(reserveAsset_);
        registry = IParticipantTaxRegistryV5(registry_);
        boundary = ISystemBoundaryV5(boundary_);
        riskGate = IRealLiquidityRiskGateV5(riskGate_);
        engine = IProfitReinvestmentEngineV5(engine_);
        ownerBeneficiary = ownerBeneficiary_;
        protocolTreasury = protocolTreasury_;
        taxEscrow = taxEscrow_;
        withholdingBps = withholdingBps_;
        minimumInvariantWad = minimumInvariantWad_;
        operator[msg.sender] = true;
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyOperator() {
        if (!operator[msg.sender]) revert Unauthorized();
        _;
    }

    function setOperator(address account, bool enabled) external onlyAdmin {
        if (account == address(0)) revert InvalidAddress();
        operator[account] = enabled;
        emit OperatorSet(account, enabled);
    }

    function setPolicy(uint256 nextWithholdingBps, uint256 nextMinimumInvariantWad)
        external
        onlyAdmin
    {
        if (nextWithholdingBps > 5_000 || nextMinimumInvariantWad < WAD) {
            revert InvalidPolicy();
        }
        withholdingBps = nextWithholdingBps;
        minimumInvariantWad = nextMinimumInvariantWad;
        emit PolicySet(nextWithholdingBps, nextMinimumInvariantWad);
    }

    function transferAdmin(address nextAdmin) external onlyAdmin {
        if (nextAdmin == address(0)) revert InvalidAddress();
        admin = nextAdmin;
    }

    function settleExternalProfit(
        address externalPayer,
        uint256 grossProfit,
        address keeperUser,
        bytes32 sourceId
    ) external onlyOperator {
        if (
            externalPayer == address(0) ||
            keeperUser == address(0) ||
            sourceId == bytes32(0)
        ) revert InvalidAddress();
        if (grossProfit == 0) revert InvalidAmount();
        if (sourceUsed[sourceId]) revert SourceAlreadyUsed();
        if (boundary.isSystemAddress(externalPayer)) revert SystemPayerForbidden();
        if (
            !registry.isEligible(ownerBeneficiary) ||
            !registry.isEligible(keeperUser)
        ) revert ParticipantNotEligible();
        if (
            !riskGate.latestPass() ||
            riskGate.latestInvariantWad() < minimumInvariantWad
        ) revert RiskInvariantNotMet();

        uint256 beforeBalance = reserveAsset.balanceOf(address(this));
        reserveAsset.safeTransferFrom(externalPayer, address(this), grossProfit);
        uint256 delta = reserveAsset.balanceOf(address(this)) - beforeBalance;
        if (delta != grossProfit) revert BalanceDeltaMismatch();

        sourceUsed[sourceId] = true;

        uint256 grossDividendPool = grossProfit * DIVIDEND_POOL_BPS / BPS;
        uint256 ownerGross =
            grossDividendPool * OWNER_SHARE_OF_DIVIDEND_BPS / BPS;
        uint256 keeperGross = grossDividendPool - ownerGross;
        uint256 ownerTax = ownerGross * withholdingBps / BPS;
        uint256 keeperTax = keeperGross * withholdingBps / BPS;
        uint256 taxWithheld = ownerTax + keeperTax;
        uint256 ownerNet = ownerGross - ownerTax;
        uint256 keeperNet = keeperGross - keeperTax;
        uint256 retained = grossProfit - grossDividendPool;

        if (taxWithheld > 0) reserveAsset.safeTransfer(taxEscrow, taxWithheld);

        uint256 compoundAmount = retained + ownerNet + keeperNet;
        reserveAsset.forceApprove(address(engine), compoundAmount);

        if (retained > 0) engine.depositRetainedProfit(retained);
        if (ownerNet > 0) engine.reinvestProfitFor(ownerBeneficiary, ownerNet);
        if (keeperNet > 0) engine.reinvestProfitFor(keeperUser, keeperNet);

        cumulativeGrossExternalProfit += grossProfit;
        cumulativeRetainedReinvestment += retained;
        cumulativeGrossDividends += grossDividendPool;
        cumulativeOwnerNetReinvestment += ownerNet;
        cumulativeKeeperNetReinvestment += keeperNet;
        cumulativeTaxWithheld += taxWithheld;

        emit ExternalProfitCompounded(
            sourceId,
            externalPayer,
            keeperUser,
            grossProfit,
            retained,
            ownerGross,
            keeperGross,
            ownerNet,
            keeperNet,
            taxWithheld
        );
    }
}

interface IEligibilityRegistryV5 {
    function isEligible(address participant) external view returns (bool);
}

interface ISynergyDexFactoryV5 {
    function isRouter(address router) external view returns (bool);
    function getPair(address tokenA, address tokenB) external view returns (address);
}

/// @notice Permissioned constant-product pair with standard PairCreated/Mint/Burn/Swap/Sync
/// event semantics. Raw events are indexable, but third-party DEX-screen branding
/// or listing still depends on the indexer's integration policy.
contract SynergyPermissionedPair is ERC20 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant SWAP_FEE_BPS = 30;
    uint256 public constant MINIMUM_LIQUIDITY = 1_000;

    address public immutable factory;
    IEligibilityRegistryV5 public immutable registry;
    address public immutable token0;
    address public immutable token1;

    uint112 private reserve0;
    uint112 private reserve1;
    uint32 private blockTimestampLast;
    bool private unlocked = true;

    error Unauthorized();
    error NotEligible();
    error InvalidAmount();
    error Expired();
    error ZeroMinimumOutput();
    error InsufficientLiquidity();
    error Slippage();
    error InvariantViolation();

    event Mint(address indexed sender, uint256 amount0, uint256 amount1);
    event Burn(
        address indexed sender,
        uint256 amount0,
        uint256 amount1,
        address indexed to
    );
    event Swap(
        address indexed sender,
        uint256 amount0In,
        uint256 amount1In,
        uint256 amount0Out,
        uint256 amount1Out,
        address indexed to
    );
    event Sync(uint112 reserve0, uint112 reserve1);

    constructor(
        address factory_,
        address registry_,
        address token0_,
        address token1_
    ) ERC20("SINERGY DEX LP", "SDX-LP") {
        factory = factory_;
        registry = IEligibilityRegistryV5(registry_);
        token0 = token0_;
        token1 = token1_;
    }

    modifier lock() {
        if (!unlocked) revert InvariantViolation();
        unlocked = false;
        _;
        unlocked = true;
    }

    modifier onlyRouter() {
        if (!ISynergyDexFactoryV5(factory).isRouter(msg.sender)) {
            revert Unauthorized();
        }
        _;
    }

    function getReserves()
        external
        view
        returns (uint112 reserve0_, uint112 reserve1_, uint32 timestamp_)
    {
        return (reserve0, reserve1, blockTimestampLast);
    }

    function mint(address participant, address to)
        external
        onlyRouter
        lock
        returns (uint256 liquidity)
    {
        _requireEligible(participant);
        _requireEligible(to);

        uint256 balance0 = IERC20(token0).balanceOf(address(this));
        uint256 balance1 = IERC20(token1).balanceOf(address(this));
        uint256 amount0 = balance0 - reserve0;
        uint256 amount1 = balance1 - reserve1;
        if (amount0 == 0 || amount1 == 0) revert InvalidAmount();

        uint256 supply = totalSupply();
        if (supply == 0) {
            uint256 root = Math.sqrt(amount0 * amount1);
            if (root <= MINIMUM_LIQUIDITY) revert InsufficientLiquidity();
            liquidity = root - MINIMUM_LIQUIDITY;
            _mint(address(1), MINIMUM_LIQUIDITY);
        } else {
            liquidity = Math.min(
                amount0 * supply / reserve0,
                amount1 * supply / reserve1
            );
        }
        if (liquidity == 0) revert InsufficientLiquidity();
        _mint(to, liquidity);
        _updateReserves(balance0, balance1);
        emit Mint(participant, amount0, amount1);
    }

    function burn(address participant, address to)
        external
        onlyRouter
        lock
        returns (uint256 amount0, uint256 amount1)
    {
        _requireEligible(participant);
        _requireEligible(to);

        uint256 liquidity = balanceOf(address(this));
        uint256 supply = totalSupply();
        if (liquidity == 0 || supply == 0) revert InvalidAmount();

        uint256 balance0 = IERC20(token0).balanceOf(address(this));
        uint256 balance1 = IERC20(token1).balanceOf(address(this));
        amount0 = liquidity * balance0 / supply;
        amount1 = liquidity * balance1 / supply;
        if (amount0 == 0 || amount1 == 0) revert InsufficientLiquidity();

        _burn(address(this), liquidity);
        IERC20(token0).safeTransfer(to, amount0);
        IERC20(token1).safeTransfer(to, amount1);

        balance0 = IERC20(token0).balanceOf(address(this));
        balance1 = IERC20(token1).balanceOf(address(this));
        _updateReserves(balance0, balance1);
        emit Burn(participant, amount0, amount1, to);
    }

    function swapExactInput(
        address participant,
        address tokenIn,
        uint256 amountIn,
        uint256 minimumAmountOut,
        address to,
        uint256 deadline
    ) external onlyRouter lock returns (uint256 amountOut) {
        _requireEligible(participant);
        _requireEligible(to);
        if (block.timestamp > deadline) revert Expired();
        if (minimumAmountOut == 0) revert ZeroMinimumOutput();
        if (amountIn == 0 || (tokenIn != token0 && tokenIn != token1)) {
            revert InvalidAmount();
        }

        bool zeroForOne = tokenIn == token0;
        uint256 reserveIn = zeroForOne ? reserve0 : reserve1;
        uint256 reserveOut = zeroForOne ? reserve1 : reserve0;
        if (reserveIn == 0 || reserveOut == 0) revert InsufficientLiquidity();

        uint256 currentIn = IERC20(tokenIn).balanceOf(address(this));
        if (currentIn < reserveIn + amountIn) revert InvalidAmount();

        uint256 amountInAfterFee = amountIn * (BPS - SWAP_FEE_BPS);
        amountOut = amountInAfterFee * reserveOut /
            (reserveIn * BPS + amountInAfterFee);
        if (amountOut < minimumAmountOut || amountOut >= reserveOut) {
            revert Slippage();
        }

        address tokenOut = zeroForOne ? token1 : token0;
        IERC20(tokenOut).safeTransfer(to, amountOut);

        uint256 balance0 = IERC20(token0).balanceOf(address(this));
        uint256 balance1 = IERC20(token1).balanceOf(address(this));
        if (balance0 * balance1 < uint256(reserve0) * uint256(reserve1)) {
            revert InvariantViolation();
        }

        _updateReserves(balance0, balance1);
        emit Swap(
            participant,
            zeroForOne ? amountIn : 0,
            zeroForOne ? 0 : amountIn,
            zeroForOne ? 0 : amountOut,
            zeroForOne ? amountOut : 0,
            to
        );
    }

    function _requireEligible(address participant) private view {
        if (!registry.isEligible(participant)) revert NotEligible();
    }

    function _updateReserves(uint256 balance0, uint256 balance1) private {
        if (balance0 > type(uint112).max || balance1 > type(uint112).max) {
            revert InvalidAmount();
        }
        reserve0 = uint112(balance0);
        reserve1 = uint112(balance1);
        blockTimestampLast = uint32(block.timestamp);
        emit Sync(reserve0, reserve1);
    }

    function _update(address from, address to, uint256 value) internal override {
        if (
            from != address(0) &&
            to != address(0) &&
            from != address(this) &&
            to != address(this) &&
            from != address(1) &&
            to != address(1)
        ) {
            if (!registry.isEligible(from) || !registry.isEligible(to)) {
                revert NotEligible();
            }
        }
        super._update(from, to, value);
    }
}

contract SynergyDexFactoryV5 {
    IEligibilityRegistryV5 public immutable registry;
    address public admin;

    mapping(address => mapping(address => address)) public getPair;
    mapping(address => bool) public isRouter;
    address[] public allPairs;

    error Unauthorized();
    error InvalidAddress();
    error PairExists();

    event PairCreated(
        address indexed token0,
        address indexed token1,
        address pair,
        uint256 allPairsLength
    );
    event RouterSet(address indexed router, bool enabled);

    constructor(address registry_) {
        if (registry_ == address(0)) revert InvalidAddress();
        admin = msg.sender;
        registry = IEligibilityRegistryV5(registry_);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    function setRouter(address router, bool enabled) external onlyAdmin {
        if (router == address(0)) revert InvalidAddress();
        isRouter[router] = enabled;
        emit RouterSet(router, enabled);
    }

    function createPair(address tokenA, address tokenB)
        external
        onlyAdmin
        returns (address pair)
    {
        if (tokenA == tokenB || tokenA == address(0) || tokenB == address(0)) {
            revert InvalidAddress();
        }
        (address token0, address token1) =
            tokenA < tokenB ? (tokenA, tokenB) : (tokenB, tokenA);
        if (getPair[token0][token1] != address(0)) revert PairExists();

        pair = address(
            new SynergyPermissionedPair(
                address(this),
                address(registry),
                token0,
                token1
            )
        );
        getPair[token0][token1] = pair;
        getPair[token1][token0] = pair;
        allPairs.push(pair);
        emit PairCreated(token0, token1, pair, allPairs.length);
    }

    function allPairsLength() external view returns (uint256) {
        return allPairs.length;
    }
}

contract SynergyDexRouterV5 {
    using SafeERC20 for IERC20;

    IEligibilityRegistryV5 public immutable registry;
    SynergyDexFactoryV5 public immutable factory;

    error NotEligible();
    error InvalidPair();
    error InvalidAmount();
    error Expired();
    error ZeroMinimumOutput();

    constructor(address registry_, address factory_) {
        registry = IEligibilityRegistryV5(registry_);
        factory = SynergyDexFactoryV5(factory_);
    }

    modifier onlyEligible() {
        if (!registry.isEligible(msg.sender)) revert NotEligible();
        _;
    }

    function addLiquidity(
        address tokenA,
        address tokenB,
        uint256 amountA,
        uint256 amountB,
        address to,
        uint256 deadline
    ) external onlyEligible returns (uint256 liquidity) {
        if (block.timestamp > deadline) revert Expired();
        if (amountA == 0 || amountB == 0) revert InvalidAmount();
        if (!registry.isEligible(to)) revert NotEligible();

        address pair = factory.getPair(tokenA, tokenB);
        if (pair == address(0)) revert InvalidPair();
        IERC20(tokenA).safeTransferFrom(msg.sender, pair, amountA);
        IERC20(tokenB).safeTransferFrom(msg.sender, pair, amountB);
        liquidity = SynergyPermissionedPair(pair).mint(msg.sender, to);
    }

    function removeLiquidity(
        address tokenA,
        address tokenB,
        uint256 liquidity,
        address to,
        uint256 deadline
    ) external onlyEligible returns (uint256 amount0, uint256 amount1) {
        if (block.timestamp > deadline) revert Expired();
        if (liquidity == 0) revert InvalidAmount();
        address pair = factory.getPair(tokenA, tokenB);
        if (pair == address(0)) revert InvalidPair();

        IERC20(pair).safeTransferFrom(msg.sender, pair, liquidity);
        (amount0, amount1) =
            SynergyPermissionedPair(pair).burn(msg.sender, to);
    }

    function swapExactTokensForTokens(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minimumAmountOut,
        address to,
        uint256 deadline
    ) external onlyEligible returns (uint256 amountOut) {
        if (block.timestamp > deadline) revert Expired();
        if (amountIn == 0) revert InvalidAmount();
        if (minimumAmountOut == 0) revert ZeroMinimumOutput();
        if (!registry.isEligible(to)) revert NotEligible();

        address pair = factory.getPair(tokenIn, tokenOut);
        if (pair == address(0)) revert InvalidPair();
        IERC20(tokenIn).safeTransferFrom(msg.sender, pair, amountIn);
        amountOut = SynergyPermissionedPair(pair).swapExactInput(
            msg.sender,
            tokenIn,
            amountIn,
            minimumAmountOut,
            to,
            deadline
        );
    }
}

/// @notice Commit-reveal order guard for protocol and permissioned-DEX orders.
/// It removes a readable order from the public mempool during the commit phase,
/// binds the reveal to its owner and rejects zero quotes/minOut. It materially
/// reduces front-run/sandwich exposure but cannot promise absolute protection
/// against validators, compromised solvers or all public-mempool conditions.
contract SynergyOrderCommitmentGuardV5 {
    uint256 public constant BPS = 10_000;

    struct Commitment {
        address owner;
        uint64 commitBlock;
        uint64 expiryBlock;
        bool consumed;
    }

    mapping(bytes32 => Commitment) public commitment;
    uint64 public immutable minimumDelayBlocks;
    uint64 public immutable maximumLifeBlocks;

    error InvalidCommitment();
    error CommitmentExists();
    error TooEarly();
    error Expired();
    error Unauthorized();
    error AlreadyConsumed();
    error ZeroMinimumOutput();
    error ZeroRouterQuote();
    error QuoteDeviation();

    event OrderCommitted(
        bytes32 indexed commitmentHash,
        address indexed owner,
        uint64 commitBlock,
        uint64 expiryBlock
    );
    event OrderConsumed(bytes32 indexed commitmentHash, address indexed owner);

    constructor(uint64 minimumDelayBlocks_, uint64 maximumLifeBlocks_) {
        if (
            minimumDelayBlocks_ == 0 ||
            maximumLifeBlocks_ <= minimumDelayBlocks_
        ) revert InvalidCommitment();
        minimumDelayBlocks = minimumDelayBlocks_;
        maximumLifeBlocks = maximumLifeBlocks_;
    }

    function hashOrder(
        address owner,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minimumAmountOut,
        uint256 deadline,
        uint256 nonce,
        bytes32 salt
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(
                block.chainid,
                address(this),
                owner,
                tokenIn,
                tokenOut,
                amountIn,
                minimumAmountOut,
                deadline,
                nonce,
                salt
            )
        );
    }

    function commitOrder(bytes32 commitmentHash) external {
        if (commitmentHash == bytes32(0)) revert InvalidCommitment();
        if (commitment[commitmentHash].owner != address(0)) {
            revert CommitmentExists();
        }
        uint64 commitBlock = uint64(block.number);
        uint64 expiryBlock = commitBlock + maximumLifeBlocks;
        commitment[commitmentHash] = Commitment({
            owner: msg.sender,
            commitBlock: commitBlock,
            expiryBlock: expiryBlock,
            consumed: false
        });
        emit OrderCommitted(
            commitmentHash,
            msg.sender,
            commitBlock,
            expiryBlock
        );
    }

    function revealAndConsume(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minimumAmountOut,
        uint256 deadline,
        uint256 nonce,
        bytes32 salt
    ) external returns (bytes32 commitmentHash) {
        if (minimumAmountOut == 0) revert ZeroMinimumOutput();
        if (block.timestamp > deadline) revert Expired();

        commitmentHash = hashOrder(
            msg.sender,
            tokenIn,
            tokenOut,
            amountIn,
            minimumAmountOut,
            deadline,
            nonce,
            salt
        );
        Commitment storage c = commitment[commitmentHash];
        if (c.owner != msg.sender) revert Unauthorized();
        if (c.consumed) revert AlreadyConsumed();
        if (block.number < uint256(c.commitBlock) + minimumDelayBlocks) {
            revert TooEarly();
        }
        if (block.number > c.expiryBlock) revert Expired();

        c.consumed = true;
        emit OrderConsumed(commitmentHash, msg.sender);
    }

    function validateQuote(
        uint256 oracleAmountOut,
        uint256 routerAmountOut,
        uint256 minimumAmountOut,
        uint256 maximumDeviationBps
    ) external pure returns (bool) {
        if (minimumAmountOut == 0) revert ZeroMinimumOutput();
        if (routerAmountOut == 0 || oracleAmountOut == 0) {
            revert ZeroRouterQuote();
        }
        if (routerAmountOut < minimumAmountOut) revert QuoteDeviation();
        if (maximumDeviationBps > BPS) revert QuoteDeviation();

        uint256 difference = routerAmountOut > oracleAmountOut
            ? routerAmountOut - oracleAmountOut
            : oracleAmountOut - routerAmountOut;
        if (difference * BPS > oracleAmountOut * maximumDeviationBps) {
            revert QuoteDeviation();
        }
        return true;
    }
}

contract MockTokenV5 is ERC20 {
    constructor(string memory name_, string memory symbol_) ERC20(name_, symbol_) {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract MockRiskGateV5 {
    bool public latestPass;
    uint256 public latestInvariantWad;

    function set(bool pass_, uint256 invariantWad_) external {
        latestPass = pass_;
        latestInvariantWad = invariantWad_;
    }
}

contract MockBoundaryV5 {
    mapping(address => bool) public isSystemAddress;

    function set(address account, bool value) external {
        isSystemAddress[account] = value;
    }
}

contract MockReinvestmentEngineV5 {
    using SafeERC20 for IERC20;

    IERC20 public immutable reserveAsset;
    address public immutable protocolTreasury;
    mapping(address => uint256) public equityShares;
    uint256 public retainedProfitCapital;
    uint256 public reinvestedDividendCapital;

    constructor(address reserveAsset_, address protocolTreasury_) {
        reserveAsset = IERC20(reserveAsset_);
        protocolTreasury = protocolTreasury_;
    }

    function reinvestProfitFor(address beneficiary, uint256 amountPol)
        external
        returns (uint256)
    {
        reserveAsset.safeTransferFrom(msg.sender, address(this), amountPol);
        equityShares[beneficiary] += amountPol;
        reinvestedDividendCapital += amountPol;
        return amountPol;
    }

    function depositRetainedProfit(uint256 amountPol)
        external
        returns (uint256)
    {
        reserveAsset.safeTransferFrom(msg.sender, address(this), amountPol);
        equityShares[protocolTreasury] += amountPol;
        retainedProfitCapital += amountPol;
        return amountPol;
    }
}
