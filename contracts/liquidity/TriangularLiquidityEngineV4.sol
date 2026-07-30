// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IQuickSwapV3PositionManagerV4 {
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
        returns (
            uint256 tokenId,
            uint128 liquidity,
            uint256 amount0,
            uint256 amount1
        );

    function increaseLiquidity(IncreaseLiquidityParams calldata params)
        external
        payable
        returns (uint128 liquidity, uint256 amount0, uint256 amount1);
}

contract TriangularInternalTokenV4 is ERC20 {
    address public immutable engine;

    error Unauthorized();

    constructor(string memory name_, string memory symbol_, address engine_)
        ERC20(name_, symbol_)
    {
        engine = engine_;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != engine) revert Unauthorized();
        _mint(to, amount);
    }

    function burn(uint256 amount) external {
        _burn(msg.sender, amount);
    }
}

/// @notice Deploys the actual triangular liquidity graph on QuickSwap Algebra V3.
/// External POL is the only capital source. Minted SYNA/SYNR stays inside
/// protocol-owned positions and therefore is inventory, not revenue.
contract TriangularLiquidityEngineV4 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant LP_BPS = 5_400;
    uint256 public constant LIQUID_RESERVE_BPS = 3_000;
    uint256 public constant INSURANCE_BPS = 1_000;
    uint256 public constant GAS_BPS = 500;
    uint256 public constant OPERATIONS_BPS = 100;
    uint256 public constant PA_SHARE_OF_LP_BPS = 6_000;
    uint256 public constant CROSS_POOL_SHARE_OF_LP_BPS = 2_500;
    uint160 public constant SQRT_PRICE_X96_ONE = 79228162514264337593543950336;

    IERC20 public immutable wpol;
    IQuickSwapV3PositionManagerV4 public immutable positionManager;
    TriangularInternalTokenV4 public immutable syna;
    TriangularInternalTokenV4 public immutable synr;

    mapping(address => uint256) public equityShares;

    uint256 public netExternalCapitalPol;
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

    error InvalidAmount();
    error ExternalRevenueInvariant();

    event KeeperDeposit(
        address indexed investor,
        uint256 grossPol,
        uint256 polSynaPositionId,
        uint256 polSynrPositionId,
        uint256 synaSynrPositionId,
        uint256 polUsedInAnchorPools
    );

    constructor(address wpol_, address positionManager_) {
        if (wpol_ == address(0) || positionManager_ == address(0)) {
            revert InvalidAmount();
        }
        wpol = IERC20(wpol_);
        positionManager = IQuickSwapV3PositionManagerV4(positionManager_);
        syna = new TriangularInternalTokenV4(
            "Synergy Capital V4",
            "SYNA-V4",
            address(this)
        );
        synr = new TriangularInternalTokenV4(
            "Synergy Reserve V4",
            "SYNR-V4",
            address(this)
        );
    }

    /// @notice Any anchor/investor may use the keeper path. The deposit creates
    /// pro-rata risk equity, not a guaranteed par debt claim. The first deposit
    /// creates the triangle; later deposits increase the existing positions.
    function depositByKeeper(uint256 amountPol) external returns (uint256 polUsed) {
        if (amountPol == 0) revert InvalidAmount();
        if (internalTransferRevenuePol != 0) revert ExternalRevenueInvariant();

        wpol.safeTransferFrom(msg.sender, address(this), amountPol);
        equityShares[msg.sender] += amountPol;
        netExternalCapitalPol += amountPol;

        uint256 lpBudget = amountPol * LP_BPS / BPS;
        uint256 desiredPolSyna = lpBudget * PA_SHARE_OF_LP_BPS / BPS;
        uint256 desiredPolSynr = lpBudget - desiredPolSyna;
        uint256 crossAmount = lpBudget * CROSS_POOL_SHARE_OF_LP_BPS / BPS;

        liquidReservePol += amountPol * LIQUID_RESERVE_BPS / BPS;
        insurancePol += amountPol * INSURANCE_BPS / BPS;
        gasReservePol += amountPol * GAS_BPS / BPS;
        operationsReservePol += amountPol * OPERATIONS_BPS / BPS;

        syna.mint(address(this), desiredPolSyna + crossAmount);
        synr.mint(address(this), desiredPolSynr + crossAmount);
        cumulativeInternalEmission += desiredPolSyna + desiredPolSynr + 2 * crossAmount;
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

        emit KeeperDeposit(
            msg.sender,
            amountPol,
            lastPolSynaPositionId,
            lastPolSynrPositionId,
            lastSynaSynrPositionId,
            polUsed
        );
    }

    function minimumAnchorPoolPol() external view returns (uint256) {
        return anchorPoolPolSyna < anchorPoolPolSynr
            ? anchorPoolPolSyna
            : anchorPoolPolSynr;
    }

    function externalEmissionLiabilityPol() external pure returns (uint256) {
        return 0;
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
            IQuickSwapV3PositionManagerV4.MintParams({
                token0: token0,
                token1: token1,
                tickLower: tickLower,
                tickUpper: tickUpper,
                amount0Desired: amount0,
                amount1Desired: amount1,
                amount0Min: 0,
                amount1Min: 0,
                recipient: address(this),
                deadline: block.timestamp
            })
        );
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
            IQuickSwapV3PositionManagerV4.IncreaseLiquidityParams({
                tokenId: tokenId,
                amount0Desired: amount0,
                amount1Desired: amount1,
                amount0Min: 0,
                amount1Min: 0,
                deadline: block.timestamp
            })
        );
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
