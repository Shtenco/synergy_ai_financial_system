// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20MockV15RevenueSource {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

/// @notice Test-only revenue source. A raw token donation changes balance but not
/// cumulativeEligibleRevenue, which lets EVM tests prove that balance alone is not
/// sufficient revenue evidence.
contract MockV15RevenueSource {
    address public immutable owner;
    mapping(address => uint256) public cumulativeEligibleRevenue;

    error Unauthorized();
    error TransferFailed();

    constructor(address owner_) {
        require(owner_ != address(0), "owner=0");
        owner = owner_;
    }

    function recognizeAndFund(address token, uint256 amount) external {
        if (msg.sender != owner) revert Unauthorized();
        if (!IERC20MockV15RevenueSource(token).transferFrom(msg.sender, address(this), amount)) {
            revert TransferFailed();
        }
        cumulativeEligibleRevenue[token] += amount;
    }

    function approveRouter(address token, address router, uint256 amount) external {
        if (msg.sender != owner) revert Unauthorized();
        if (!IERC20MockV15RevenueSource(token).approve(router, amount)) revert TransferFailed();
    }
}
