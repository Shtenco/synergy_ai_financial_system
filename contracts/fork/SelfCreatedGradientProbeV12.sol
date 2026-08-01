// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract GradientProbeSyntheticV12 is ERC20 {
    address public owner;

    error Unauthorized();

    constructor(address owner_) ERC20("Gradient Probe Synthetic", "gpSYN") {
        owner = owner_;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external onlyOwner {
        _burn(from, amount);
    }
}

contract GradientProbePoolV12 {
    using SafeERC20 for IERC20;

    uint256 public constant FEE_NUMERATOR = 997;
    uint256 public constant FEE_DENOMINATOR = 1000;

    IERC20 public immutable synthetic;
    IERC20 public immutable liquid;
    uint112 private reserveSynthetic;
    uint112 private reserveLiquid;
    bool private unlocked = true;

    error InvalidAmount();
    error InsufficientLiquidity();
    error Slippage();
    error Reentrancy();

    event Sync(uint112 reserveSynthetic, uint112 reserveLiquid);
    event SwapSyntheticForLiquid(uint256 syntheticIn, uint256 liquidOut);
    event SwapLiquidForSynthetic(uint256 liquidIn, uint256 syntheticOut);

    constructor(address synthetic_, address liquid_) {
        synthetic = IERC20(synthetic_);
        liquid = IERC20(liquid_);
    }

    modifier lock() {
        if (!unlocked) revert Reentrancy();
        unlocked = false;
        _;
        unlocked = true;
    }

    function getReserves() external view returns (uint112, uint112) {
        return (reserveSynthetic, reserveLiquid);
    }

    function seed(uint256 syntheticAmount, uint256 liquidAmount) external lock {
        if (syntheticAmount == 0 || liquidAmount == 0) revert InvalidAmount();
        synthetic.safeTransferFrom(msg.sender, address(this), syntheticAmount);
        liquid.safeTransferFrom(msg.sender, address(this), liquidAmount);
        _sync();
    }

    function sync() external lock {
        _sync();
    }

    function quoteLiquidOut(uint256 syntheticIn) public view returns (uint256) {
        if (syntheticIn == 0) return 0;
        uint256 amountInWithFee = syntheticIn * FEE_NUMERATOR;
        return amountInWithFee * uint256(reserveLiquid)
            / (uint256(reserveSynthetic) * FEE_DENOMINATOR + amountInWithFee);
    }

    function quoteLiquidForExactSynthetic(uint256 syntheticOut)
        public
        view
        returns (uint256)
    {
        if (syntheticOut == 0 || syntheticOut >= reserveSynthetic) {
            revert InsufficientLiquidity();
        }
        uint256 numerator =
            uint256(reserveLiquid) * syntheticOut * FEE_DENOMINATOR;
        uint256 denominator =
            (uint256(reserveSynthetic) - syntheticOut) * FEE_NUMERATOR;
        return numerator / denominator + 1;
    }

    function swapExactSyntheticForLiquid(
        uint256 syntheticIn,
        uint256 minLiquidOut,
        address to
    ) external lock returns (uint256 liquidOut) {
        if (syntheticIn == 0) revert InvalidAmount();
        liquidOut = quoteLiquidOut(syntheticIn);
        if (liquidOut == 0 || liquidOut < minLiquidOut) revert Slippage();
        synthetic.safeTransferFrom(msg.sender, address(this), syntheticIn);
        liquid.safeTransfer(to, liquidOut);
        _sync();
        emit SwapSyntheticForLiquid(syntheticIn, liquidOut);
    }

    function swapLiquidForExactSynthetic(
        uint256 syntheticOut,
        uint256 maxLiquidIn,
        address to
    ) external lock returns (uint256 liquidIn) {
        liquidIn = quoteLiquidForExactSynthetic(syntheticOut);
        if (liquidIn > maxLiquidIn) revert Slippage();
        liquid.safeTransferFrom(msg.sender, address(this), liquidIn);
        synthetic.safeTransfer(to, syntheticOut);
        _sync();
        emit SwapLiquidForSynthetic(liquidIn, syntheticOut);
    }

    function _sync() internal {
        uint256 syntheticBalance = synthetic.balanceOf(address(this));
        uint256 liquidBalance = liquid.balanceOf(address(this));
        if (syntheticBalance > type(uint112).max || liquidBalance > type(uint112).max) {
            revert InsufficientLiquidity();
        }
        reserveSynthetic = uint112(syntheticBalance);
        reserveLiquid = uint112(liquidBalance);
        emit Sync(reserveSynthetic, reserveLiquid);
    }
}
