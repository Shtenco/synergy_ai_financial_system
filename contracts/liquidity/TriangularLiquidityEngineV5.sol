// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IQuickSwapV3PositionManagerV5 {
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

    struct IncreaseLiquidityParams {
        uint256 tokenId;
        uint256 amount0Desired;
        uint256 amount1Desired;
        uint256 amount0Min;
        uint256 amount1Min;
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

    function increaseLiquidity(IncreaseLiquidityParams calldata params)
        external
        payable
        returns (uint128 liquidity, uint256 amount0, uint256 amount1);
}

/// @notice Public representative token. Wallet-to-wallet transfers are disabled:
/// every transfer must touch a trusted venue or protocol endpoint. This reduces
/// uncontrolled routing but does not claim impossible "perfect" public-mempool MEV protection.
contract SynergyRepresentativeTokenV5 is ERC20 {
    address public immutable engine;
    mapping(address => bool) public trustedEndpoint;

    error Unauthorized();
    error RestrictedTransfer();

    constructor(string memory name_, string memory symbol_, address engine_)
        ERC20(name_, symbol_)
    {
        engine = engine_;
        trustedEndpoint[engine_] = true;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != engine) revert Unauthorized();
        _mint(to, amount);
    }

    function burn(uint256 amount) external {
        _burn(msg.sender, amount);
    }

    function setTrustedEndpoint(address endpoint, bool trusted) external {
        if (msg.sender != engine) revert Unauthorized();
        trustedEndpoint[endpoint] = trusted;
    }

    function _update(address from, address to, uint256 value) internal override {
        if (
            from != address(0) &&
            to != address(0) &&
            !trustedEndpoint[from] &&
            !trustedEndpoint[to]
        ) revert RestrictedTransfer();
        super._update(from, to, value);
    }
}

/// @notice V5 capital engine:
/// - original external POL and reinvested realised profit are tracked separately;
/// - public QuickSwap liquidity uses the representative SYNA token;
/// - internal SYNA/SYNR notional never counts as external revenue or capital;
/// - every mint/increase uses non-zero minimum amounts and a finite deadline.
contract TriangularLiquidityEngineV5 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant LP_BPS = 5_400;
    uint256 public constant LIQUID_RESERVE_BPS = 3_000;
    uint256 public constant INSURANCE_BPS = 1_000;
    uint256 public constant GAS_BPS = 500;
    uint256 public constant OPERATIONS_BPS = 100;
    uint256 public constant POL_SYNA_SHARE_OF_LP_BPS = 6_000;
    uint256 public constant CROSS_POOL_SHARE_OF_LP_BPS = 2_500;
    uint256 public constant POSITION_MIN_BPS = 9_800;
    uint256 public constant DEADLINE_SECONDS = 300;
    uint160 public constant SQRT_PRICE_X96_ONE = 79228162514264337593543950336;

    IERC20 public immutable wpol;
    IQuickSwapV3PositionManagerV5 public immutable positionManager;
    SynergyRepresentativeTokenV5 public immutable syna;
    SynergyRepresentativeTokenV5 public immutable synr;
    address public immutable admin;
    address public immutable protocolTreasury;

    address public profitController;

    mapping(address => uint256) public equityShares;

    uint256 public originalExternalCapitalPol;
    uint256 public reinvestedProfitCapitalPol;
    uint256 public retainedProfitCapitalPol;
    uint256 public totalBackedCapitalPol;
    uint256 public liquidReservePol;
    uint256 public insurancePol;
    uint256 public gasReservePol;
    uint256 public operationsReservePol;
    uint256 public anchorPoolPolSyna;
    uint256 public anchorPoolPolSynr;
    uint256 public crossPoolInternalNotional;
    uint256 public cumulativeInternalEmission;
    uint256 public internalTransferRevenuePol;

    uint256 public lastPolSynaPositionId;
    uint256 public lastPolSynrPositionId;
    uint256 public lastSynaSynrPositionId;
    address public polSynaPool;
    address public polSynrPool;
    address public synaSynrPool;

    error Unauthorized();
    error InvalidAmount();
    error InvalidAddress();
    error ControllerAlreadySet();
    error ExternalRevenueInvariant();
    error PositionSlippage();

    event ProfitControllerSet(address indexed controller);
    event CapitalAllocated(
        address indexed beneficiary,
        address indexed payer,
        uint8 indexed capitalClass,
        uint256 grossPol,
        uint256 polUsedInAnchorPools
    );
    event RepresentativeEndpointSet(address indexed endpoint, bool trusted);
    event RepresentativeInventoryMinted(address indexed to, uint256 amount);

    constructor(
        address wpol_,
        address positionManager_,
        address protocolTreasury_
    ) {
        if (
            wpol_ == address(0) ||
            positionManager_ == address(0) ||
            protocolTreasury_ == address(0)
        ) revert InvalidAddress();

        admin = msg.sender;
        protocolTreasury = protocolTreasury_;
        wpol = IERC20(wpol_);
        positionManager = IQuickSwapV3PositionManagerV5(positionManager_);

        syna = new SynergyRepresentativeTokenV5(
            "SYNA - SYNERGY Representative",
            "SYNA",
            address(this)
        );
        synr = new SynergyRepresentativeTokenV5(
            "SYNERGY Reserve",
            "SYNR",
            address(this)
        );
        syna.setTrustedEndpoint(address(positionManager), true);
        synr.setTrustedEndpoint(address(positionManager), true);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyProfitController() {
        if (msg.sender != profitController) revert Unauthorized();
        _;
    }

    function setProfitController(address controller) external onlyAdmin {
        if (controller == address(0)) revert InvalidAddress();
        if (profitController != address(0)) revert ControllerAlreadySet();
        profitController = controller;
        emit ProfitControllerSet(controller);
    }

    function setRepresentativeEndpoint(address endpoint, bool trusted)
        external
        onlyAdmin
    {
        if (endpoint == address(0)) revert InvalidAddress();
        syna.setTrustedEndpoint(endpoint, trusted);
        synr.setTrustedEndpoint(endpoint, trusted);
        emit RepresentativeEndpointSet(endpoint, trusted);
    }

    /// @notice Inventory is protocol inventory, not external revenue and not a debt claim.
    function mintRepresentativeInventory(address to, uint256 amount)
        external
        onlyAdmin
    {
        if (to == address(0) || amount == 0) revert InvalidAmount();
        syna.mint(to, amount);
        cumulativeInternalEmission += amount;
        emit RepresentativeInventoryMinted(to, amount);
    }

    function depositByKeeper(uint256 amountPol)
        external
        returns (uint256 polUsed)
    {
        polUsed = _allocate(msg.sender, msg.sender, amountPol, 0);
        originalExternalCapitalPol += amountPol;
    }

    /// @notice Net owner/keeper dividend is never paid out: it is converted into
    /// additional risk equity and productive liquidity.
    function reinvestProfitFor(address beneficiary, uint256 amountPol)
        external
        onlyProfitController
        returns (uint256 polUsed)
    {
        polUsed = _allocate(beneficiary, msg.sender, amountPol, 1);
        reinvestedProfitCapitalPol += amountPol;
    }

    /// @notice The retained portion of realised profit compounds for the protocol.
    function depositRetainedProfit(uint256 amountPol)
        external
        onlyProfitController
        returns (uint256 polUsed)
    {
        polUsed = _allocate(protocolTreasury, msg.sender, amountPol, 2);
        retainedProfitCapitalPol += amountPol;
    }

    function minimumAnchorPoolPol() external view returns (uint256) {
        return anchorPoolPolSyna < anchorPoolPolSynr
            ? anchorPoolPolSyna
            : anchorPoolPolSynr;
    }

    function externalEmissionLiabilityPol() external pure returns (uint256) {
        return 0;
    }

    function _allocate(
        address beneficiary,
        address payer,
        uint256 amountPol,
        uint8 capitalClass
    ) private returns (uint256 polUsed) {
        if (beneficiary == address(0) || amountPol == 0) revert InvalidAmount();
        if (internalTransferRevenuePol != 0) revert ExternalRevenueInvariant();

        wpol.safeTransferFrom(payer, address(this), amountPol);
        equityShares[beneficiary] += amountPol;
        totalBackedCapitalPol += amountPol;

        uint256 lpBudget = amountPol * LP_BPS / BPS;
        uint256 desiredPolSyna =
            lpBudget * POL_SYNA_SHARE_OF_LP_BPS / BPS;
        uint256 desiredPolSynr = lpBudget - desiredPolSyna;
        uint256 crossAmount =
            lpBudget * CROSS_POOL_SHARE_OF_LP_BPS / BPS;

        liquidReservePol += amountPol * LIQUID_RESERVE_BPS / BPS;
        insurancePol += amountPol * INSURANCE_BPS / BPS;
        gasReservePol += amountPol * GAS_BPS / BPS;
        operationsReservePol += amountPol * OPERATIONS_BPS / BPS;

        syna.mint(address(this), desiredPolSyna + crossAmount);
        synr.mint(address(this), desiredPolSynr + crossAmount);
        cumulativeInternalEmission +=
            desiredPolSyna + desiredPolSynr + 2 * crossAmount;
        crossPoolInternalNotional += crossAmount;

        uint256 polUsedSyna;
        uint256 polUsedSynr;
        uint256 ignoredCrossUsed;

        if (lastPolSynaPositionId == 0) {
            (polSynaPool, lastPolSynaPositionId, polUsedSyna) = _mintPosition(
                address(wpol),
                address(syna),
                desiredPolSyna,
                desiredPolSyna,
                -2_400,
                2_400
            );
            (polSynrPool, lastPolSynrPositionId, polUsedSynr) = _mintPosition(
                address(wpol),
                address(synr),
                desiredPolSynr,
                desiredPolSynr,
                -3_000,
                3_000
            );
            (synaSynrPool, lastSynaSynrPositionId, ignoredCrossUsed) = _mintPosition(
                address(syna),
                address(synr),
                crossAmount,
                crossAmount,
                -3_600,
                3_600
            );
            syna.setTrustedEndpoint(polSynaPool, true);
            synr.setTrustedEndpoint(polSynrPool, true);
            syna.setTrustedEndpoint(synaSynrPool, true);
            synr.setTrustedEndpoint(synaSynrPool, true);
        } else {
            polUsedSyna = _increasePosition(
                lastPolSynaPositionId,
                address(wpol),
                address(syna),
                desiredPolSyna,
                desiredPolSyna
            );
            polUsedSynr = _increasePosition(
                lastPolSynrPositionId,
                address(wpol),
                address(synr),
                desiredPolSynr,
                desiredPolSynr
            );
            ignoredCrossUsed = _increasePosition(
                lastSynaSynrPositionId,
                address(syna),
                address(synr),
                crossAmount,
                crossAmount
            );
        }
        ignoredCrossUsed;

        anchorPoolPolSyna += polUsedSyna;
        anchorPoolPolSynr += polUsedSynr;
        polUsed = polUsedSyna + polUsedSynr;

        emit CapitalAllocated(
            beneficiary,
            payer,
            capitalClass,
            amountPol,
            polUsed
        );
    }

    function _mintPosition(
        address tokenA,
        address tokenB,
        uint256 amountA,
        uint256 amountB,
        int24 tickLower,
        int24 tickUpper
    )
        private
        returns (address pool, uint256 tokenId, uint256 amountAUsed)
    {
        (address token0, address token1, uint256 amount0, uint256 amount1) =
            tokenA < tokenB
                ? (tokenA, tokenB, amountA, amountB)
                : (tokenB, tokenA, amountB, amountA);

        pool = positionManager.createAndInitializePoolIfNecessary(
            token0,
            token1,
            SQRT_PRICE_X96_ONE
        );
        _approvePair(token0, token1, amount0, amount1);

        uint256 used0;
        uint256 used1;
        (tokenId,, used0, used1) = positionManager.mint(
            IQuickSwapV3PositionManagerV5.MintParams({
                token0: token0,
                token1: token1,
                tickLower: tickLower,
                tickUpper: tickUpper,
                amount0Desired: amount0,
                amount1Desired: amount1,
                amount0Min: amount0 * POSITION_MIN_BPS / BPS,
                amount1Min: amount1 * POSITION_MIN_BPS / BPS,
                recipient: address(this),
                deadline: block.timestamp + DEADLINE_SECONDS
            })
        );
        if (
            used0 < amount0 * POSITION_MIN_BPS / BPS ||
            used1 < amount1 * POSITION_MIN_BPS / BPS
        ) revert PositionSlippage();
        amountAUsed = tokenA == token0 ? used0 : used1;
    }

    function _increasePosition(
        uint256 tokenId,
        address tokenA,
        address tokenB,
        uint256 amountA,
        uint256 amountB
    ) private returns (uint256 amountAUsed) {
        (address token0, address token1, uint256 amount0, uint256 amount1) =
            tokenA < tokenB
                ? (tokenA, tokenB, amountA, amountB)
                : (tokenB, tokenA, amountB, amountA);
        _approvePair(token0, token1, amount0, amount1);

        uint256 used0;
        uint256 used1;
        (, used0, used1) = positionManager.increaseLiquidity(
            IQuickSwapV3PositionManagerV5.IncreaseLiquidityParams({
                tokenId: tokenId,
                amount0Desired: amount0,
                amount1Desired: amount1,
                amount0Min: amount0 * POSITION_MIN_BPS / BPS,
                amount1Min: amount1 * POSITION_MIN_BPS / BPS,
                deadline: block.timestamp + DEADLINE_SECONDS
            })
        );
        if (
            used0 < amount0 * POSITION_MIN_BPS / BPS ||
            used1 < amount1 * POSITION_MIN_BPS / BPS
        ) revert PositionSlippage();
        amountAUsed = tokenA == token0 ? used0 : used1;
    }

    function _approvePair(
        address token0,
        address token1,
        uint256 amount0,
        uint256 amount1
    ) private {
        IERC20(token0).forceApprove(address(positionManager), amount0);
        IERC20(token1).forceApprove(address(positionManager), amount1);
    }
}
