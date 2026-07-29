// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract ProtectedReserveGuard {
    address public immutable owner;
    mapping(address=>bool) public protected;
    mapping(address=>uint256) public baseline;

    error Unauthorized();
    error ReserveViolation();

    constructor(address owner_){owner=owner_;}

    function register(address token) external {
        if(msg.sender!=owner) revert Unauthorized();
        protected[token]=true;
        baseline[token]=IERC20(token).balanceOf(address(this));
    }

    function checkpoint(address token) external view {
        if(protected[token] && IERC20(token).balanceOf(address(this))<baseline[token])
            revert ReserveViolation();
    }
}
