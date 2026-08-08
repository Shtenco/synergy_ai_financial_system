// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Synthetic dollar liability. Only ElasticLiquidityEngine can expand/contract supply.
contract USDx {
    string public constant name = "SynthL1 USDx";
    string public constant symbol = "USDx";
    uint8 public constant decimals = 18;

    address public owner;
    address public engine;
    bool public engineFrozen;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);
    event EngineSet(address indexed engine);

    error Unauthorized();
    error ZeroAddress();
    error Frozen();
    error InsufficientBalance();
    error InsufficientAllowance();

    constructor(address owner_) {
        if (owner_ == address(0)) revert ZeroAddress();
        owner = owner_;
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyEngine() { if (msg.sender != engine) revert Unauthorized(); _; }

    function setEngine(address engine_, bool freeze) external onlyOwner {
        if (engineFrozen) revert Frozen();
        if (engine_ == address(0)) revert ZeroAddress();
        engine = engine_;
        if (freeze) engineFrozen = true;
        emit EngineSet(engine_);
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

    function mint(address to, uint256 amount) external onlyEngine {
        if (to == address(0)) revert ZeroAddress();
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    /// @notice Engine may burn only USDx it actually holds.
    function burnHeld(uint256 amount) external onlyEngine {
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
