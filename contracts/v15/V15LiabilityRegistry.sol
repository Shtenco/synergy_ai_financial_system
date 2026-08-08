// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV15LiabilitySource {
    function currentLiability(bytes32 id) external view returns (uint256 amount);
}

/// @notice Generic registry of externally enforceable liabilities.
/// Unit values are contractual/redemption values in 1e18 USD, not market-cap marks.
/// Manual liabilities are freshness-gated: stale obligations make accounting revert
/// rather than silently retaining an old optimistic number.
contract V15LiabilityRegistry {
    struct LiabilityConfig {
        bool enabled;
        uint8 decimals;
        uint16 baseStressBps;
        address source;
        uint64 manualUpdatedAt;
        uint256 manualAmount;
        uint256 unitValue1e18;
    }

    uint256 public constant MAX_LIABILITIES = 64;
    uint16 public constant MAX_STRESS_BPS = 50_000;

    address public owner;
    uint32 public manualMaxAge = 300;
    mapping(address => bool) public reporter;
    bytes32[] public liabilityIds;
    mapping(bytes32 => LiabilityConfig) public liability;

    event ReporterSet(address indexed reporter, bool allowed);
    event ManualMaxAgeSet(uint32 maxAge);
    event LiabilityAdded(bytes32 indexed id, uint8 decimals, uint256 unitValue1e18, uint16 stressBps, address source);
    event LiabilityAmountSet(bytes32 indexed id, uint256 amount, uint64 updatedAt);
    event LiabilityValueSet(bytes32 indexed id, uint256 unitValue1e18);
    event LiabilityStressSet(bytes32 indexed id, uint16 stressBps);
    event LiabilitySourceSet(bytes32 indexed id, address indexed source);
    event LiabilityEnabled(bytes32 indexed id, bool enabled);

    error Unauthorized();
    error BadConfig();
    error SourceManaged();
    error StaleLiability(bytes32 id);

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

    function setManualMaxAge(uint32 age) external onlyOwner {
        if (age == 0) revert BadConfig();
        manualMaxAge = age;
        emit ManualMaxAgeSet(age);
    }

    function addLiability(
        bytes32 id,
        uint8 decimals_,
        uint256 unitValue1e18_,
        uint16 stressBps_,
        address source_,
        uint256 manualAmount_
    ) external onlyOwner {
        if (
            id == bytes32(0) || liability[id].unitValue1e18 != 0 || decimals_ > 36 ||
            unitValue1e18_ == 0 || stressBps_ < 10_000 || stressBps_ > MAX_STRESS_BPS ||
            liabilityIds.length >= MAX_LIABILITIES
        ) revert BadConfig();
        liability[id] = LiabilityConfig({
            enabled: true,
            decimals: decimals_,
            baseStressBps: stressBps_,
            source: source_,
            manualUpdatedAt: source_ == address(0) ? uint64(block.timestamp) : uint64(0),
            manualAmount: manualAmount_,
            unitValue1e18: unitValue1e18_
        });
        liabilityIds.push(id);
        emit LiabilityAdded(id, decimals_, unitValue1e18_, stressBps_, source_);
    }

    function setManualAmount(bytes32 id, uint256 amount) external onlyReporter {
        LiabilityConfig storage c = liability[id];
        if (c.unitValue1e18 == 0) revert BadConfig();
        if (c.source != address(0)) revert SourceManaged();
        c.manualAmount = amount;
        c.manualUpdatedAt = uint64(block.timestamp);
        emit LiabilityAmountSet(id, amount, c.manualUpdatedAt);
    }

    function setUnitValue1e18(bytes32 id, uint256 value) external onlyOwner {
        if (value == 0 || liability[id].unitValue1e18 == 0) revert BadConfig();
        liability[id].unitValue1e18 = value;
        emit LiabilityValueSet(id, value);
    }

    function setStressBps(bytes32 id, uint16 bps) external onlyOwner {
        if (liability[id].unitValue1e18 == 0 || bps < 10_000 || bps > MAX_STRESS_BPS) revert BadConfig();
        liability[id].baseStressBps = bps;
        emit LiabilityStressSet(id, bps);
    }

    function setSource(bytes32 id, address source) external onlyOwner {
        LiabilityConfig storage c = liability[id];
        if (c.unitValue1e18 == 0) revert BadConfig();
        c.source = source;
        // Switching back to manual mode starts a fresh reporting window from the
        // currently stored manual amount. Governance/reporters should immediately
        // refresh it if the amount itself may have changed.
        c.manualUpdatedAt = source == address(0) ? uint64(block.timestamp) : uint64(0);
        emit LiabilitySourceSet(id, source);
    }

    function setEnabled(bytes32 id, bool enabled) external onlyOwner {
        LiabilityConfig storage c = liability[id];
        if (c.unitValue1e18 == 0) revert BadConfig();
        c.enabled = enabled;
        if (enabled && c.source == address(0)) c.manualUpdatedAt = uint64(block.timestamp);
        emit LiabilityEnabled(id, enabled);
    }

    function currentAmount(bytes32 id) public view returns (uint256) {
        LiabilityConfig memory c = liability[id];
        if (!c.enabled) return 0;
        if (c.source != address(0)) return IV15LiabilitySource(c.source).currentLiability(id);
        if (
            c.manualUpdatedAt == 0 ||
            block.timestamp > uint256(c.manualUpdatedAt) + uint256(manualMaxAge)
        ) revert StaleLiability(id);
        return c.manualAmount;
    }

    function canonicalValue1e18(bytes32 id) public view returns (uint256) {
        LiabilityConfig memory c = liability[id];
        if (!c.enabled) return 0;
        uint256 amount = currentAmount(id);
        uint256 scale = 10 ** uint256(c.decimals);
        return (amount * c.unitValue1e18) / scale;
    }

    function riskValue1e18(bytes32 id) public view returns (uint256) {
        LiabilityConfig memory c = liability[id];
        if (!c.enabled) return 0;
        return (canonicalValue1e18(id) * uint256(c.baseStressBps)) / 10_000;
    }

    function totalCanonicalLiabilities1e18() public view returns (uint256 total) {
        for (uint256 i; i < liabilityIds.length; ++i) total += canonicalValue1e18(liabilityIds[i]);
    }

    function totalRiskLiabilities1e18() public view returns (uint256 total) {
        for (uint256 i; i < liabilityIds.length; ++i) total += riskValue1e18(liabilityIds[i]);
    }

    function liabilityCount() external view returns (uint256) { return liabilityIds.length; }
}
