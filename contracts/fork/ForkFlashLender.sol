// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20ForkLender {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

interface IFlashBorrowerForkLender {
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external returns (bool);
}

/// @notice Deterministic Aave-compatible lender used only for fork economics.
/// It lends the real Polygon WPOL token and enforces atomic repayment plus fee.
/// The economic result therefore doesn't depend on Aave reserve governance flags.
contract ForkFlashLender {
    uint256 public constant BPS = 10_000;

    IERC20ForkLender public immutable asset;
    uint16 public immutable premiumBps;
    address public immutable addressesProvider;

    error UnsupportedAsset();
    error InsufficientLiquidity();
    error CallbackFailed();
    error RepaymentFailed();

    event FlashLoan(
        address indexed receiver,
        uint256 amount,
        uint256 premium,
        uint256 lenderBalanceBefore,
        uint256 lenderBalanceAfter
    );

    constructor(IERC20ForkLender asset_, uint16 premiumBps_) {
        asset = asset_;
        premiumBps = premiumBps_;
        addressesProvider = address(this);
    }

    function ADDRESSES_PROVIDER() external view returns (address) {
        return addressesProvider;
    }

    function flashLoanSimple(
        address receiverAddress,
        address borrowedAsset,
        uint256 amount,
        bytes calldata params,
        uint16
    ) external {
        if (borrowedAsset != address(asset)) revert UnsupportedAsset();

        uint256 beforeBalance = asset.balanceOf(address(this));
        if (amount == 0 || beforeBalance < amount) revert InsufficientLiquidity();

        uint256 premium = amount * premiumBps / BPS;
        if (!asset.transfer(receiverAddress, amount)) revert RepaymentFailed();

        bool ok = IFlashBorrowerForkLender(receiverAddress).executeOperation(
            borrowedAsset,
            amount,
            premium,
            receiverAddress,
            params
        );
        if (!ok) revert CallbackFailed();

        if (!asset.transferFrom(receiverAddress, address(this), amount + premium)) {
            revert RepaymentFailed();
        }

        uint256 afterBalance = asset.balanceOf(address(this));
        if (afterBalance < beforeBalance + premium) revert RepaymentFailed();

        emit FlashLoan(receiverAddress, amount, premium, beforeBalance, afterBalance);
    }
}
