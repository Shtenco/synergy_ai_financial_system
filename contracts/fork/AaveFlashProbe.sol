// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20FlashProbe {
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IAavePoolFlashProbe {
    function ADDRESSES_PROVIDER() external view returns (address);
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

/// @notice Minimal receiver used to prove whether the pinned Aave Polygon
/// reserve itself supports flashLoanSimple independently from QE logic.
contract AaveFlashProbe {
    IAavePoolFlashProbe public immutable pool;
    IERC20FlashProbe public immutable asset;
    address public immutable addressesProvider;
    uint256 public lastAmount;
    uint256 public lastPremium;

    error Unauthorized();
    error ApprovalFailed();

    constructor(IAavePoolFlashProbe pool_, IERC20FlashProbe asset_) {
        pool = pool_;
        asset = asset_;
        addressesProvider = pool_.ADDRESSES_PROVIDER();
    }

    function ADDRESSES_PROVIDER() external view returns (address) {
        return addressesProvider;
    }

    function POOL() external view returns (address) {
        return address(pool);
    }

    function run(uint256 amount) external {
        pool.flashLoanSimple(address(this), address(asset), amount, bytes(""), 0);
    }

    function executeOperation(
        address borrowedAsset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata
    ) external returns (bool) {
        if (
            msg.sender != address(pool)
                || initiator != address(this)
                || borrowedAsset != address(asset)
        ) revert Unauthorized();

        lastAmount = amount;
        lastPremium = premium;
        if (!asset.approve(address(pool), amount + premium)) revert ApprovalFailed();
        return true;
    }
}
