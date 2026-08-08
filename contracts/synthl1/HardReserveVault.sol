// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IERC20Reserve {
    function balanceOf(address) external view returns (uint256);
    function decimals() external view returns (uint8);
}

/// @notice Custody for real externally redeemable stable assets (USDC in the reference deployment).
/// No internal token mint can increase this balance.
contract HardReserveVault {
    using SafeTransferLib for address;

    address public immutable hardToken;
    uint8 public immutable hardDecimals;

    address public owner;
    address public controller;
    bool public controllerFrozen;

    uint16 public maxSingleOutflowBps = 5_000;
    uint256 public cumulativeDeposited;
    uint256 public cumulativeWithdrawn;

    event ControllerSet(address indexed controller);
    event Deposit(address indexed from, uint256 amount);
    event TransferOut(address indexed to, uint256 amount);
    event MaxOutflowSet(uint16 bps);

    error Unauthorized();
    error BadConfig();
    error Frozen();
    error OutflowTooLarge();

    constructor(address hardToken_, address owner_) {
        if (hardToken_ == address(0) || owner_ == address(0)) revert BadConfig();
        hardToken = hardToken_;
        hardDecimals = IERC20Reserve(hardToken_).decimals();
        owner = owner_;
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyController() { if (msg.sender != controller) revert Unauthorized(); _; }

    function setController(address controller_, bool freeze) external onlyOwner {
        if (controllerFrozen) revert Frozen();
        if (controller_ == address(0)) revert BadConfig();
        controller = controller_;
        if (freeze) controllerFrozen = true;
        emit ControllerSet(controller_);
    }

    function setMaxSingleOutflowBps(uint16 bps) external onlyOwner {
        if (bps == 0 || bps > 10_000) revert BadConfig();
        maxSingleOutflowBps = bps;
        emit MaxOutflowSet(bps);
    }

    function deposit(uint256 amount) external {
        if (amount == 0) revert BadConfig();
        hardToken.safeTransferFrom(msg.sender, address(this), amount);
        cumulativeDeposited += amount;
        emit Deposit(msg.sender, amount);
    }

    function transferOut(address to, uint256 amount) external onlyController {
        if (to == address(0) || amount == 0) revert BadConfig();
        uint256 b = balance();
        if (amount > (b * maxSingleOutflowBps) / 10_000) revert OutflowTooLarge();
        cumulativeWithdrawn += amount;
        hardToken.safeTransfer(to, amount);
        emit TransferOut(to, amount);
    }

    function balance() public view returns (uint256) {
        return IERC20Reserve(hardToken).balanceOf(address(this));
    }
}
