// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice EVM prototype of SynthL1 native CORE.
/// Anyone may burn only CORE held by their own address.
contract CORE {
    string public constant name = "SynthL1 CORE";
    string public constant symbol = "CORE";
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);

    error ZeroAddress();
    error InsufficientBalance();
    error InsufficientAllowance();

    constructor(address genesisHolder, uint256 genesisSupply) {
        if (genesisHolder == address(0)) revert ZeroAddress();
        totalSupply = genesisSupply;
        balanceOf[genesisHolder] = genesisSupply;
        emit Transfer(address(0), genesisHolder, genesisSupply);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 a = allowance[from][msg.sender];
        if (a != type(uint256).max) {
            if (a < amount) revert InsufficientAllowance();
            unchecked { allowance[from][msg.sender] = a - amount; }
            emit Approval(from, msg.sender, allowance[from][msg.sender]);
        }
        _transfer(from, to, amount);
        return true;
    }

    function burn(uint256 amount) external {
        uint256 b = balanceOf[msg.sender];
        if (b < amount) revert InsufficientBalance();
        unchecked { balanceOf[msg.sender] = b - amount; }
        totalSupply -= amount;
        emit Transfer(msg.sender, address(0), amount);
    }

    function _transfer(address from, address to, uint256 amount) internal {
        if (to == address(0)) revert ZeroAddress();
        uint256 b = balanceOf[from];
        if (b < amount) revert InsufficientBalance();
        unchecked {
            balanceOf[from] = b - amount;
            balanceOf[to] += amount;
        }
        emit Transfer(from, to, amount);
    }
}
