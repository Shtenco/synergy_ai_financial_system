// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Consensus-facing USD price hub for the multi-asset SynthL1 graph.
/// Prices are 1e18 USD per whole token. In a production L1, reporters should be
/// replaced/controlled by validator consensus, signed attestations or hardened adapters.
contract PriceOracleHub {
    struct PriceData {
        uint192 price1e18;
        uint64 updatedAt;
    }

    address public owner;
    mapping(address => bool) public reporter;
    mapping(address => PriceData) private priceData;
    uint32 public maxAge = 60;

    event ReporterSet(address indexed reporter, bool allowed);
    event PriceUpdated(address indexed token, uint256 price1e18, uint64 timestamp);
    event MaxAgeSet(uint32 maxAge);

    error Unauthorized();
    error BadPrice();
    error StalePrice(address token);
    error BadConfig();

    constructor(address owner_) {
        if (owner_ == address(0)) revert BadConfig();
        owner = owner_;
        reporter[owner_] = true;
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyReporter() { if (!reporter[msg.sender]) revert Unauthorized(); _; }

    function setReporter(address who, bool allowed) external onlyOwner {
        if (who == address(0)) revert BadConfig();
        reporter[who] = allowed;
        emit ReporterSet(who, allowed);
    }

    function setMaxAge(uint32 age) external onlyOwner {
        if (age == 0) revert BadPrice();
        maxAge = age;
        emit MaxAgeSet(age);
    }

    function updatePrice(address token, uint256 price) external onlyReporter {
        _update(token, price);
    }

    function updatePrices(address[] calldata tokens, uint256[] calldata prices) external onlyReporter {
        uint256 n = tokens.length;
        if (n == 0 || n != prices.length || n > 32) revert BadConfig();
        for (uint256 i = 0; i < n; ++i) _update(tokens[i], prices[i]);
    }

    function price1e18(address token) external view returns (uint256) {
        PriceData memory p = priceData[token];
        if (p.price1e18 == 0 || block.timestamp > uint256(p.updatedAt) + maxAge) {
            revert StalePrice(token);
        }
        return uint256(p.price1e18);
    }

    function rawPrice(address token) external view returns (uint256 price, uint64 updatedAt, bool fresh) {
        PriceData memory p = priceData[token];
        price = uint256(p.price1e18);
        updatedAt = p.updatedAt;
        fresh = price != 0 && block.timestamp <= uint256(updatedAt) + maxAge;
    }

    function _update(address token, uint256 price) internal {
        if (token == address(0) || price == 0 || price > type(uint192).max) revert BadPrice();
        priceData[token] = PriceData(uint192(price), uint64(block.timestamp));
        emit PriceUpdated(token, price, uint64(block.timestamp));
    }
}
