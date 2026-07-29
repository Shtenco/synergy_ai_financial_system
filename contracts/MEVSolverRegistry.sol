// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract MEVSolverRegistry {
    uint256 public constant MIN_BOND = 1 ether;
    address public immutable governor;

    struct Solver {
        uint256 bond;
        uint256 executions;
        uint256 feesPaid;
        bool active;
    }

    mapping(address => Solver) public solvers;

    error Unauthorized();
    error InvalidBond();

    event Registered(address indexed solver, uint256 bond);
    event Slashed(address indexed solver, uint256 amount);

    constructor(address governor_) {
        governor = governor_;
    }

    function register() external payable {
        if (msg.value < MIN_BOND) revert InvalidBond();
        solvers[msg.sender] = Solver(msg.value, 0, 0, true);
        emit Registered(msg.sender, msg.value);
    }

    function slash(address solver) external {
        if (msg.sender != governor) revert Unauthorized();
        uint256 amount = solvers[solver].bond;
        solvers[solver].active = false;
        solvers[solver].bond = 0;
        emit Slashed(solver, amount);
    }

    function record(address solver, uint256 fee) external {
        if (msg.sender != governor) revert Unauthorized();
        solvers[solver].executions++;
        solvers[solver].feesPaid += fee;
    }
}
