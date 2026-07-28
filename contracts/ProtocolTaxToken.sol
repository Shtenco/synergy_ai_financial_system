// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Reference migration token with a non-bypassable protocol tax on
/// every ordinary transfer, including pair/router transfers. This is not a bot
/// classifier: all users bear the same tax and DEX integrations must model it.
contract ProtocolTaxToken is ERC20, Ownable {
    uint16 public constant MIN_TAX_BPS = 2_000;
    uint16 public constant MAX_TAX_BPS = 3_000;
    uint16 public taxBps;
    address public treasury;

    event TaxChanged(uint16 taxBps);
    event TreasuryChanged(address indexed treasury);

    constructor(
        string memory name_, string memory symbol_, address owner_, address treasury_,
        uint16 taxBps_, uint256 initialSupply
    ) ERC20(name_, symbol_) Ownable(owner_) {
        require(treasury_ != address(0));
        _setTax(taxBps_);
        treasury = treasury_;
        _mint(owner_, initialSupply);
    }

    function setTax(uint16 next) external onlyOwner { _setTax(next); }

    function setTreasury(address next) external onlyOwner {
        require(next != address(0));
        treasury = next;
        emit TreasuryChanged(next);
    }

    function mint(address to, uint256 amount) external onlyOwner { _mint(to, amount); }

    function _setTax(uint16 next) internal {
        require(next >= MIN_TAX_BPS && next <= MAX_TAX_BPS, "tax outside 20-30%");
        taxBps = next;
        emit TaxChanged(next);
    }

    function _update(address from, address to, uint256 value) internal override {
        if (from == address(0) || to == address(0) || value == 0) {
            super._update(from, to, value);
            return;
        }
        uint256 tax = value * taxBps / 10_000;
        super._update(from, treasury, tax);
        super._update(from, to, value - tax);
    }
}
