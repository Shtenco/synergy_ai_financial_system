// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IParticipantRegistryV7 {
    function isEligible(address participant) external view returns (bool);
}

interface ISynergyFactoryV7 {
    function getPair(address tokenA, address tokenB) external view returns (address);
}

interface IQuickSwapFactoryV7 {
    function poolByPair(address tokenA, address tokenB) external view returns (address);
}

interface IQuickSwapPositionManagerV7 {
    struct MintParams {
        address token0;
        address token1;
        int24 tickLower;
        int24 tickUpper;
        uint256 amount0Desired;
        uint256 amount1Desired;
        uint256 amount0Min;
        uint256 amount1Min;
        address recipient;
        uint256 deadline;
    }

    function createAndInitializePoolIfNecessary(
        address token0,
        address token1,
        uint160 sqrtPriceX96
    ) external payable returns (address pool);

    function mint(MintParams calldata params)
        external
        payable
        returns (uint256 tokenId, uint128 liquidity, uint256 amount0, uint256 amount1);
}

/// @notice Representative SYNA: the public pool can only touch the protected gateway
/// or explicitly trusted infrastructure. Wallet-to-wallet transfers are forbidden.
contract SynergyRepresentativeTokenV7 is ERC20 {
    address public immutable engine;
    address public protectedGateway;
    mapping(address => bool) public publicPool;
    mapping(address => bool) public internalPair;
    mapping(address => bool) public infrastructure;

    error Unauthorized();
    error RestrictedTransfer();

    constructor(address engine_) ERC20("SYNA - SYNERGY Representative", "SYNA") {
        engine = engine_;
        infrastructure[engine_] = true;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != engine) revert Unauthorized();
        _mint(to, amount);
    }

    function configureGateway(address gateway) external {
        if (msg.sender != engine || gateway == address(0)) revert Unauthorized();
        protectedGateway = gateway;
        infrastructure[gateway] = true;
    }

    function setPublicPool(address pool, bool enabled) external {
        if (msg.sender != engine) revert Unauthorized();
        publicPool[pool] = enabled;
    }

    function setInternalPair(address pair, bool enabled) external {
        if (msg.sender != engine) revert Unauthorized();
        internalPair[pair] = enabled;
        infrastructure[pair] = enabled;
    }

    function setInfrastructure(address account, bool enabled) external {
        if (msg.sender != engine) revert Unauthorized();
        infrastructure[account] = enabled;
    }

    function _update(address from, address to, uint256 amount) internal override {
        if (from != address(0) && to != address(0)) {
            bool publicTouch = publicPool[from] || publicPool[to];
            bool internalTouch = internalPair[from] || internalPair[to];
            if (publicTouch) {
                address other = publicPool[from] ? to : from;
                if (other != protectedGateway && !infrastructure[other]) {
                    revert RestrictedTransfer();
                }
            } else if (internalTouch) {
                if (!infrastructure[msg.sender] && !infrastructure[from] && !infrastructure[to]) {
                    revert RestrictedTransfer();
                }
            } else if (!infrastructure[from] && !infrastructure[to]) {
                revert RestrictedTransfer();
            }
        }
        super._update(from, to, amount);
    }
}

contract SynergyInternalReserveTokenV7 is ERC20 {
    address public immutable engine;
    mapping(address => bool) public internalEndpoint;

    error Unauthorized();
    error InternalOnly();

    constructor(address engine_) ERC20("SYNERGY Reserve", "SYNR") {
        engine = engine_;
        internalEndpoint[engine_] = true;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != engine) revert Unauthorized();
        _mint(to, amount);
    }

    function setInternalEndpoint(address endpoint, bool enabled) external {
        if (msg.sender != engine) revert Unauthorized();
        internalEndpoint[endpoint] = enabled;
    }

    function _update(address from, address to, uint256 amount) internal override {
        if (
            from != address(0) &&
            to != address(0) &&
            !internalEndpoint[from] &&
            !internalEndpoint[to] &&
            !internalEndpoint[msg.sender]
        ) revert InternalOnly();
        super._update(from, to, amount);
    }
}

/// @notice Exact topology: three internal SINERGY pools and one public QuickSwap WPOL/SYNA.
contract SynergyTopologyV7 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant MIN_POSITION_BPS = 9_700;
    uint160 public constant SQRT_PRICE_X96_ONE = 79228162514264337593543950336;

    IERC20 public immutable wpol;
    IERC20 public immutable usdt;
    IParticipantRegistryV7 public immutable participantRegistry;
    ISynergyFactoryV7 public immutable internalFactory;
    IQuickSwapFactoryV7 public immutable quickSwapFactory;
    IQuickSwapPositionManagerV7 public immutable positionManager;
    SynergyRepresentativeTokenV7 public immutable syna;
    SynergyInternalReserveTokenV7 public immutable synr;
    address public immutable admin;

    address public internalPolSyna;
    address public internalPolSynr;
    address public internalSynaSynr;
    address public publicQuickSwapPolSyna;
    uint256 public publicPositionId;
    uint256 public externalCapitalPol;
    uint256 public internalQeNotionalPol;
    uint256 public externalQtBurnPol;

    error Unauthorized();
    error InvalidAddress();
    error InvalidTopology();
    error Ineligible();
    error AlreadyConfigured();

    event InternalTopologyConfigured(address polSyna, address polSynr, address synaSynr);
    event PublicRepresentativePoolCreated(address pool, uint256 positionId, uint256 polAmount);
    event QEAllocated(uint256 notionalPol);
    event QTRecorded(uint256 externalLiabilityBurnPol);

    constructor(
        address wpol_,
        address usdt_,
        address participantRegistry_,
        address internalFactory_,
        address quickSwapFactory_,
        address positionManager_
    ) {
        if (
            wpol_ == address(0) || usdt_ == address(0) || participantRegistry_ == address(0) ||
            internalFactory_ == address(0) || quickSwapFactory_ == address(0) || positionManager_ == address(0)
        ) revert InvalidAddress();
        admin = msg.sender;
        wpol = IERC20(wpol_);
        usdt = IERC20(usdt_);
        participantRegistry = IParticipantRegistryV7(participantRegistry_);
        internalFactory = ISynergyFactoryV7(internalFactory_);
        quickSwapFactory = IQuickSwapFactoryV7(quickSwapFactory_);
        positionManager = IQuickSwapPositionManagerV7(positionManager_);
        syna = new SynergyRepresentativeTokenV7(address(this));
        synr = new SynergyInternalReserveTokenV7(address(this));
        syna.setInfrastructure(positionManager_, true);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    function configureInternalTopology(address internalRouter) external onlyAdmin {
        if (internalPolSyna != address(0)) revert AlreadyConfigured();
        address ps = internalFactory.getPair(address(wpol), address(syna));
        address pr = internalFactory.getPair(address(wpol), address(synr));
        address sr = internalFactory.getPair(address(syna), address(synr));
        if (ps == address(0) || pr == address(0) || sr == address(0)) revert InvalidTopology();
        internalPolSyna = ps;
        internalPolSynr = pr;
        internalSynaSynr = sr;
        syna.setInternalPair(ps, true);
        syna.setInternalPair(sr, true);
        syna.setInfrastructure(internalRouter, true);
        synr.setInternalEndpoint(pr, true);
        synr.setInternalEndpoint(sr, true);
        synr.setInternalEndpoint(internalRouter, true);
        emit InternalTopologyConfigured(ps, pr, sr);
    }

    function setProtectedGateway(address gateway) external onlyAdmin {
        syna.configureGateway(gateway);
    }

    /// @dev Creates only public WPOL/SYNA. Local-token WPOL/SYNR and SYNA/SYNR
    /// must stay absent from QuickSwap and remain internal SINERGY DEX pairs.
    function createPublicRepresentativePool(uint256 polAmount)
        external
        onlyAdmin
        returns (address pool, uint256 tokenId)
    {
        if (publicQuickSwapPolSyna != address(0) || polAmount == 0) revert InvalidTopology();
        if (!participantRegistry.isEligible(msg.sender)) revert Ineligible();
        wpol.safeTransferFrom(msg.sender, address(this), polAmount);
        syna.mint(address(this), polAmount);

        address token0 = address(wpol) < address(syna) ? address(wpol) : address(syna);
        address token1 = address(wpol) < address(syna) ? address(syna) : address(wpol);
        pool = positionManager.createAndInitializePoolIfNecessary(token0, token1, SQRT_PRICE_X96_ONE);
        syna.setPublicPool(pool, true);
        IERC20(address(wpol)).forceApprove(address(positionManager), polAmount);
        IERC20(address(syna)).forceApprove(address(positionManager), polAmount);

        uint128 liquidity;
        uint256 used0;
        uint256 used1;
        (tokenId, liquidity, used0, used1) = positionManager.mint(
            IQuickSwapPositionManagerV7.MintParams({
                token0: token0,
                token1: token1,
                tickLower: -2_400,
                tickUpper: 2_400,
                amount0Desired: polAmount,
                amount1Desired: polAmount,
                amount0Min: polAmount * MIN_POSITION_BPS / BPS,
                amount1Min: polAmount * MIN_POSITION_BPS / BPS,
                recipient: address(this),
                deadline: block.timestamp + 300
            })
        );
        liquidity; used0; used1;
        publicQuickSwapPolSyna = pool;
        publicPositionId = tokenId;
        externalCapitalPol += polAmount;

        if (
            quickSwapFactory.poolByPair(address(wpol), address(synr)) != address(0) ||
            quickSwapFactory.poolByPair(address(syna), address(synr)) != address(0)
        ) revert InvalidTopology();
        emit PublicRepresentativePoolCreated(pool, tokenId, polAmount);
    }

    function recordQE(uint256 notionalPol) external onlyAdmin {
        internalQeNotionalPol += notionalPol;
        emit QEAllocated(notionalPol);
    }

    function recordQT(uint256 externalLiabilityBurnPol) external onlyAdmin {
        externalQtBurnPol += externalLiabilityBurnPol;
        emit QTRecorded(externalLiabilityBurnPol);
    }
}

contract ExternalExitPoolRegistryV7 {
    enum PoolKind { QUICKSWAP_V2, QUICKSWAP_V3, OTHER }
    struct ExitPool {
        address pool;
        address token0;
        address token1;
        PoolKind kind;
        uint256 minimumToken0Balance;
        uint256 minimumToken1Balance;
        bool enabled;
    }

    address public immutable admin;
    address public immutable wpol;
    address public immutable usdt;
    mapping(address => ExitPool) public exitPool;
    address[] public allExitPools;

    error Unauthorized();
    error InvalidPool();

    constructor(address wpol_, address usdt_) {
        admin = msg.sender;
        wpol = wpol_;
        usdt = usdt_;
    }

    function whitelistExitPool(
        address pool,
        address token0,
        address token1,
        PoolKind kind,
        uint256 minimum0,
        uint256 minimum1
    ) external {
        if (msg.sender != admin) revert Unauthorized();
        bool correctPair =
            (token0 == wpol && token1 == usdt) || (token0 == usdt && token1 == wpol);
        if (!correctPair || pool == address(0) || pool.code.length == 0) revert InvalidPool();
        exitPool[pool] = ExitPool(pool, token0, token1, kind, minimum0, minimum1, true);
        allExitPools.push(pool);
    }

    function validate(address pool) public view returns (bool) {
        ExitPool memory p = exitPool[pool];
        return p.enabled && IERC20(p.token0).balanceOf(pool) >= p.minimumToken0Balance &&
            IERC20(p.token1).balanceOf(pool) >= p.minimumToken1Balance;
    }

    function count() external view returns (uint256) {
        return allExitPools.length;
    }
}

/// @notice Consolidated route gate. QE notional never counts as revenue; every
/// internal value loss is deducted before a cycle can be accepted.
contract SynergyGraphProfitGateV7 {
    IParticipantRegistryV7 public immutable registry;
    ExternalExitPoolRegistryV7 public immutable exits;
    address public immutable wpol;
    address public immutable usdt;
    address public admin;
    mapping(address => bool) public keeper;
    mapping(address => bool) public internalPool;
    mapping(address => bool) public publicRepresentativePool;
    mapping(bytes32 => uint64) public committedAtBlock;
    mapping(bytes32 => bool) public consumed;

    struct CycleProof {
        address settlementAsset;
        uint256 amountIn;
        uint256 amountOut;
        uint256 gasCost;
        uint256 poolFees;
        uint256 slippageCost;
        uint256 flashPremium;
        uint256 internalValueLoss;
        uint256 qeNotional;
        uint256 qtExternalBurn;
        address[] pools;
        bool[] externalEdge;
    }

    error Unauthorized();
    error Ineligible();
    error InvalidRoute();
    error TooEarly();
    error NoExternalProfit();
    error QERevenueForbidden();

    event CycleCommitted(bytes32 indexed routeHash, address indexed keeper, uint64 blockNumber);
    event CycleAccepted(bytes32 indexed routeHash, uint256 externalNetProfit, uint256 qeNotional, uint256 qtBurn);

    constructor(address registry_, address exits_, address wpol_, address usdt_) {
        registry = IParticipantRegistryV7(registry_);
        exits = ExternalExitPoolRegistryV7(exits_);
        wpol = wpol_;
        usdt = usdt_;
        admin = msg.sender;
        keeper[msg.sender] = true;
    }

    function setKeeper(address account, bool enabled) external {
        if (msg.sender != admin) revert Unauthorized();
        keeper[account] = enabled;
    }

    function setInternalPool(address pool, bool enabled) external {
        if (msg.sender != admin) revert Unauthorized();
        internalPool[pool] = enabled;
    }

    function setPublicRepresentativePool(address pool, bool enabled) external {
        if (msg.sender != admin) revert Unauthorized();
        publicRepresentativePool[pool] = enabled;
    }

    function hashProof(CycleProof calldata proof, uint256 nonce, bytes32 salt)
        public
        view
        returns (bytes32)
    {
        return keccak256(abi.encode(block.chainid, address(this), msg.sender, proof, nonce, salt));
    }

    function commit(bytes32 routeHash) external {
        if (!keeper[msg.sender] || !registry.isEligible(msg.sender)) revert Ineligible();
        committedAtBlock[routeHash] = uint64(block.number);
        emit CycleCommitted(routeHash, msg.sender, uint64(block.number));
    }

    function revealAndAccept(CycleProof calldata proof, uint256 nonce, bytes32 salt)
        external
        returns (uint256 externalNetProfit)
    {
        if (!keeper[msg.sender] || !registry.isEligible(msg.sender)) revert Ineligible();
        bytes32 routeHash = hashProof(proof, nonce, salt);
        uint64 committed = committedAtBlock[routeHash];
        if (committed == 0 || block.number <= committed) revert TooEarly();
        if (consumed[routeHash]) revert InvalidRoute();
        if (proof.settlementAsset != wpol && proof.settlementAsset != usdt) revert InvalidRoute();
        if (proof.pools.length < 2 || proof.pools.length != proof.externalEdge.length) revert InvalidRoute();

        bool hasInternal;
        bool hasExternal;
        for (uint256 i; i < proof.pools.length; ++i) {
            if (proof.externalEdge[i]) {
                if (!exits.validate(proof.pools[i]) && !publicRepresentativePool[proof.pools[i]]) {
                    revert InvalidRoute();
                }
                hasExternal = true;
            } else {
                if (!internalPool[proof.pools[i]]) revert InvalidRoute();
                hasInternal = true;
            }
        }
        if (!hasInternal || !hasExternal) revert InvalidRoute();

        uint256 costs = proof.gasCost + proof.poolFees + proof.slippageCost +
            proof.flashPremium + proof.internalValueLoss;
        if (proof.amountOut <= proof.amountIn + costs) revert NoExternalProfit();
        externalNetProfit = proof.amountOut - proof.amountIn - costs;
        if (proof.qeNotional > 0 && proof.internalValueLoss == 0) revert QERevenueForbidden();
        if (proof.qtExternalBurn > externalNetProfit) revert InvalidRoute();

        consumed[routeHash] = true;
        emit CycleAccepted(routeHash, externalNetProfit, proof.qeNotional, proof.qtExternalBurn);
    }
}

/// @notice Enforceable public-edge controls: commit-reveal, non-zero minOut and
/// router quote, oracle deviation bound, deadline and sandwich-loss cap.
contract PublicRepresentativeProtectionV7 {
    uint256 public constant BPS = 10_000;
    uint64 public immutable minimumDelayBlocks;
    mapping(bytes32 => uint64) public committedAt;
    mapping(bytes32 => bool) public consumed;

    error InvalidOrder();
    error TooEarly();
    error ZeroRouterQuote();
    error QuoteDeviation();
    error SandwichBound();

    constructor(uint64 minimumDelayBlocks_) {
        if (minimumDelayBlocks_ == 0) revert InvalidOrder();
        minimumDelayBlocks = minimumDelayBlocks_;
    }

    function hashOrder(
        address owner,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minOut,
        uint256 oracleOut,
        uint256 maxDeviationBps,
        uint256 maxSandwichLossBps,
        uint256 deadline,
        uint256 nonce,
        bytes32 salt
    ) public view returns (bytes32) {
        return keccak256(abi.encode(
            block.chainid,
            address(this),
            owner,
            tokenIn,
            tokenOut,
            amountIn,
            minOut,
            oracleOut,
            maxDeviationBps,
            maxSandwichLossBps,
            deadline,
            nonce,
            salt
        ));
    }

    function commit(bytes32 orderHash) external {
        if (orderHash == bytes32(0)) revert InvalidOrder();
        committedAt[orderHash] = uint64(block.number);
    }

    function revealValidate(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minOut,
        uint256 oracleOut,
        uint256 routerOut,
        uint256 postTradeQuote,
        uint256 maxDeviationBps,
        uint256 maxSandwichLossBps,
        uint256 deadline,
        uint256 nonce,
        bytes32 salt
    ) external returns (bytes32 orderHash) {
        if (minOut == 0 || amountIn == 0 || block.timestamp > deadline) revert InvalidOrder();
        if (routerOut == 0 || oracleOut == 0 || postTradeQuote == 0) revert ZeroRouterQuote();
        orderHash = hashOrder(
            msg.sender,
            tokenIn,
            tokenOut,
            amountIn,
            minOut,
            oracleOut,
            maxDeviationBps,
            maxSandwichLossBps,
            deadline,
            nonce,
            salt
        );
        uint64 committed = committedAt[orderHash];
        if (committed == 0 || block.number < uint256(committed) + minimumDelayBlocks) revert TooEarly();
        if (consumed[orderHash]) revert InvalidOrder();
        if (routerOut < minOut || maxDeviationBps > BPS || maxSandwichLossBps > BPS) {
            revert QuoteDeviation();
        }
        uint256 difference = routerOut > oracleOut ? routerOut - oracleOut : oracleOut - routerOut;
        if (difference * BPS > oracleOut * maxDeviationBps) revert QuoteDeviation();
        uint256 sandwichLoss = routerOut > postTradeQuote ? routerOut - postTradeQuote : 0;
        if (sandwichLoss * BPS > routerOut * maxSandwichLossBps) revert SandwichBound();
        consumed[orderHash] = true;
    }
}
