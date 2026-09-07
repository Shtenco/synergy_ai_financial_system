// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract MockControlledEmissionTokenV1 {
    string public constant name = "Escrow Test SYNA";
    string public constant symbol = "eSYNA";
    uint8 public constant decimals = 18;

    address public immutable owner;
    address public controller;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event ControllerSet(address indexed controller);

    modifier onlyOwner() {
        require(msg.sender == owner, "OWNER_ONLY");
        _;
    }

    modifier onlyController() {
        require(msg.sender == controller, "CONTROLLER_ONLY");
        _;
    }

    constructor(address owner_) {
        require(owner_ != address(0), "ZERO_OWNER");
        owner = owner_;
    }

    function setController(address controller_) external onlyOwner {
        require(controller == address(0), "CONTROLLER_ALREADY_SET");
        require(controller_ != address(0), "ZERO_CONTROLLER");
        controller = controller_;
        emit ControllerSet(controller_);
    }

    function mint(address to, uint256 amount) external onlyController returns (uint256 minted) {
        require(to != address(0) && amount > 0, "BAD_MINT");
        balanceOf[to] += amount;
        totalSupply += amount;
        emit Transfer(address(0), to, amount);
        return amount;
    }

    function burn(address from, uint256 amount) external onlyController returns (uint256 burned) {
        require(balanceOf[from] >= amount, "BURN_BALANCE");
        balanceOf[from] -= amount;
        totalSupply -= amount;
        emit Transfer(from, address(0), amount);
        return amount;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(to != address(0), "ZERO_TO");
        require(balanceOf[msg.sender] >= amount, "BALANCE");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }
}
