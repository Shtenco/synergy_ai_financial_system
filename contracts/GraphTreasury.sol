// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {GraphPolicy} from "./GraphPolicy.sol";

interface IBurnMintToken is IERC20 {
    function burn(uint256 amount) external;
    function mint(address to, uint256 amount) external;
}

/// @notice Asset custody boundary. Every movement consumes one timelocked policy.
contract GraphTreasury {
    using SafeERC20 for IERC20;
    GraphPolicy public immutable policy;
    address public immutable governor;
    mapping(address => bool) public modules;

    error Unauthorized();

    constructor(GraphPolicy policy_, address governor_) {
        policy = policy_;
        governor = governor_;
    }

    function setModule(address module, bool enabled) external {
        if (msg.sender != governor) revert Unauthorized();
        modules[module] = enabled;
    }

    function release(uint256 proposalId, address token, address to, uint256 amount) external {
        if (!modules[msg.sender]) revert Unauthorized();
        GraphPolicy.Proposal memory p = policy.consume(proposalId, msg.sender);
        require(p.target == msg.sender && p.amount == amount, "policy mismatch");
        IERC20(token).safeTransfer(to, amount);
    }

    function burn(uint256 proposalId, IBurnMintToken token, uint256 amount) external {
        if (!modules[msg.sender]) revert Unauthorized();
        GraphPolicy.Proposal memory p = policy.consume(proposalId, msg.sender);
        require(p.target == msg.sender && p.amount == amount, "policy mismatch");
        token.burn(amount);
    }
}
