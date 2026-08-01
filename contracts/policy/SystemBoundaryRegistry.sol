// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Defines the accounting boundary of the consolidated SYNERGY system.
/// Transfers between two registered addresses are internal and cannot be
/// recognized as realized revenue or consolidated NAV growth.
contract SystemBoundaryRegistry {
    address public admin;
    address public pendingAdmin;
    mapping(address => bool) public isSystemAddress;

    error Unauthorized();
    error InvalidAddress();
    error NoChange();

    event SystemAddressSet(address indexed account, bool isSystem);
    event AdminTransferStarted(address indexed currentAdmin, address indexed pendingAdmin);
    event AdminTransferred(address indexed previousAdmin, address indexed newAdmin);

    constructor(address admin_) {
        if (admin_ == address(0)) revert InvalidAddress();
        admin = admin_;
        isSystemAddress[admin_] = true;
        emit SystemAddressSet(admin_, true);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    function setSystemAddress(address account, bool value) external onlyAdmin {
        if (account == address(0)) revert InvalidAddress();
        if (isSystemAddress[account] == value) revert NoChange();
        isSystemAddress[account] = value;
        emit SystemAddressSet(account, value);
    }

    function setSystemAddresses(address[] calldata accounts, bool value) external onlyAdmin {
        for (uint256 i; i < accounts.length; ++i) {
            address account = accounts[i];
            if (account == address(0)) revert InvalidAddress();
            if (isSystemAddress[account] != value) {
                isSystemAddress[account] = value;
                emit SystemAddressSet(account, value);
            }
        }
    }

    function isInternalTransfer(address from, address to) external view returns (bool) {
        return isSystemAddress[from] && isSystemAddress[to];
    }

    function startAdminTransfer(address nextAdmin) external onlyAdmin {
        if (nextAdmin == address(0)) revert InvalidAddress();
        pendingAdmin = nextAdmin;
        emit AdminTransferStarted(admin, nextAdmin);
    }

    function acceptAdmin() external {
        if (msg.sender != pendingAdmin) revert Unauthorized();
        address previous = admin;
        admin = msg.sender;
        pendingAdmin = address(0);
        isSystemAddress[msg.sender] = true;
        emit AdminTransferred(previous, msg.sender);
        emit SystemAddressSet(msg.sender, true);
    }
}
