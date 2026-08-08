// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Consensus-facing executable-price root.
/// In production, validator consensus / signed attestations feed this contract/module.
contract PriceOracleHub {
    address public owner;
    mapping(address => bool) public reporter;

    uint256 public internalCorePrice1e18;
    uint256 public externalCorePrice1e18;
    uint64 public updatedAt;
    uint32 public maxAge = 60;

    event ReporterSet(address indexed reporter, bool allowed);
    event PricesUpdated(uint256 internalPrice, uint256 externalPrice, uint64 timestamp);
    event MaxAgeSet(uint32 maxAge);

    error Unauthorized();
    error BadPrice();
    error Stale();

    constructor(address owner_) {
        owner = owner_;
        reporter[owner_] = true;
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyReporter() { if (!reporter[msg.sender]) revert Unauthorized(); _; }

    function setReporter(address who, bool allowed) external onlyOwner {
        reporter[who] = allowed;
        emit ReporterSet(who, allowed);
    }

    function setMaxAge(uint32 age) external onlyOwner {
        if (age == 0) revert BadPrice();
        maxAge = age;
        emit MaxAgeSet(age);
    }

    function updatePrices(uint256 internalPrice, uint256 externalPrice) external onlyReporter {
        if (internalPrice == 0 || externalPrice == 0) revert BadPrice();
        internalCorePrice1e18 = internalPrice;
        externalCorePrice1e18 = externalPrice;
        updatedAt = uint64(block.timestamp);
        emit PricesUpdated(internalPrice, externalPrice, uint64(block.timestamp));
    }

    function requireFresh() public view {
        if (updatedAt == 0 || block.timestamp > uint256(updatedAt) + maxAge) revert Stale();
    }

    function basisBps() external view returns (int256) {
        requireFresh();
        uint256 i = internalCorePrice1e18;
        uint256 e = externalCorePrice1e18;
        if (e >= i) return int256(((e - i) * 10_000) / i);
        return -int256(((i - e) * 10_000) / e);
    }
}
