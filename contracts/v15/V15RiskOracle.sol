// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV15RiskCanonicalOracle {
    function price1e18(address token) external view returns (uint256);
}

interface IV15ValidatedRiskAnchor is IV15RiskCanonicalOracle {
    function oracleValidationReady() external view returns (bool);
}

/// @notice Conservative risk marks and finite stress scenarios for V15.
/// Bootstrap risk reads may use the constructor oracle, but monetary expansion
/// must be gated by validatedAnchorReady() in V15SolvencyController. Once frozen,
/// the anchor is immutable and is expected to be V15EconomicLedger itself.
contract V15RiskOracle {
    struct RiskData {
        uint192 twap1e18;
        uint192 exit1e18;
        uint64 updatedAt;
        uint16 haircutBps;
    }
    struct Scenario {
        bytes32 name;
        uint16 liabilityStressBps;
        uint256 fixedSystemCost1e18;
        bool enabled;
    }
    struct ScenarioAsset {
        uint16 priceStressBps;
        uint16 liquidityBps;
    }

    uint256 public constant MAX_SCENARIOS = 16;
    address public owner;
    address public immutable canonicalOracle;
    address public validatedCanonicalAnchor;
    bool public validatedCanonicalAnchorFrozen;
    mapping(address => bool) public reporter;
    mapping(address => RiskData) public riskData;
    Scenario[] private scenarios;
    mapping(uint256 => mapping(address => ScenarioAsset)) public scenarioAsset;
    uint32 public maxAge = 300;

    event ReporterSet(address indexed reporter, bool allowed);
    event RiskDataSet(address indexed token, uint256 twap1e18, uint256 exit1e18);
    event HaircutSet(address indexed token, uint16 haircutBps);
    event ValidatedCanonicalAnchorSet(address indexed anchor, bool frozen);
    event ScenarioAdded(uint256 indexed id, bytes32 indexed name, uint16 liabilityStressBps, uint256 fixedCost1e18);
    event ScenarioSet(uint256 indexed id, uint16 liabilityStressBps, uint256 fixedCost1e18, bool enabled);
    event ScenarioAssetSet(uint256 indexed id, address indexed token, uint16 priceStressBps, uint16 liquidityBps);
    event MaxAgeSet(uint32 age);

    error Unauthorized();
    error BadConfig();
    error Frozen();
    error StaleRiskData(address token);
    error InvalidValidatedAnchor();

    constructor(address owner_, address canonicalOracle_) {
        if (owner_ == address(0) || canonicalOracle_ == address(0)) revert BadConfig();
        owner = owner_;
        canonicalOracle = canonicalOracle_;
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
        if (age == 0) revert BadConfig();
        maxAge = age;
        emit MaxAgeSet(age);
    }

    /// @notice One-way anchor to independently validated Economic marks.
    /// Recommended anchor: V15EconomicLedger after its validation oracle is frozen.
    function setValidatedCanonicalAnchor(address anchor, bool freeze) external onlyOwner {
        if (validatedCanonicalAnchorFrozen) revert Frozen();
        if (anchor == address(0) || anchor.code.length == 0) revert BadConfig();
        bool ready;
        try IV15ValidatedRiskAnchor(anchor).oracleValidationReady() returns (bool ok) {
            ready = ok;
        } catch {
            revert InvalidValidatedAnchor();
        }
        if (!ready) revert InvalidValidatedAnchor();
        validatedCanonicalAnchor = anchor;
        if (freeze) validatedCanonicalAnchorFrozen = true;
        emit ValidatedCanonicalAnchorSet(anchor, validatedCanonicalAnchorFrozen);
    }

    function validatedAnchorReady() public view returns (bool) {
        address anchor = validatedCanonicalAnchor;
        if (anchor == address(0) || !validatedCanonicalAnchorFrozen) return false;
        try IV15ValidatedRiskAnchor(anchor).oracleValidationReady() returns (bool ready) {
            return ready;
        } catch {
            return false;
        }
    }

    function _canonicalPrice1e18(address token) internal view returns (uint256) {
        address anchor = validatedCanonicalAnchor;
        if (anchor != address(0)) return IV15RiskCanonicalOracle(anchor).price1e18(token);
        return IV15RiskCanonicalOracle(canonicalOracle).price1e18(token);
    }

    function setHaircut(address token, uint16 haircutBps) external onlyOwner {
        if (token == address(0) || haircutBps == 0 || haircutBps > 10_000) revert BadConfig();
        riskData[token].haircutBps = haircutBps;
        emit HaircutSet(token, haircutBps);
    }

    function setRiskData(address token, uint256 twap, uint256 exitPrice) external onlyReporter {
        RiskData storage r = riskData[token];
        if (
            token == address(0) || twap == 0 || exitPrice == 0 ||
            twap > type(uint192).max || exitPrice > type(uint192).max || r.haircutBps == 0
        ) revert BadConfig();
        r.twap1e18 = uint192(twap);
        r.exit1e18 = uint192(exitPrice);
        r.updatedAt = uint64(block.timestamp);
        emit RiskDataSet(token, twap, exitPrice);
    }

    function riskPrice1e18(address token) public view returns (uint256) {
        RiskData memory r = riskData[token];
        if (r.updatedAt == 0 || block.timestamp > uint256(r.updatedAt) + maxAge) revert StaleRiskData(token);
        uint256 canonical = _canonicalPrice1e18(token);
        uint256 p = canonical < uint256(r.twap1e18) ? canonical : uint256(r.twap1e18);
        return p < uint256(r.exit1e18) ? p : uint256(r.exit1e18);
    }

    function baseRiskValue1e18(address token, uint256 amount, uint8 decimals_) public view returns (uint256) {
        RiskData memory r = riskData[token];
        uint256 gross = (amount * riskPrice1e18(token)) / (10 ** uint256(decimals_));
        return (gross * uint256(r.haircutBps)) / 10_000;
    }

    function addScenario(bytes32 name, uint16 liabilityStressBps, uint256 fixedCost1e18) external onlyOwner returns (uint256 id) {
        if (
            name == bytes32(0) || liabilityStressBps < 10_000 || liabilityStressBps > 50_000 ||
            scenarios.length >= MAX_SCENARIOS
        ) revert BadConfig();
        id = scenarios.length;
        scenarios.push(Scenario(name, liabilityStressBps, fixedCost1e18, true));
        emit ScenarioAdded(id, name, liabilityStressBps, fixedCost1e18);
    }

    function setScenario(uint256 id, uint16 liabilityStressBps, uint256 fixedCost1e18, bool enabled) external onlyOwner {
        if (id >= scenarios.length || liabilityStressBps < 10_000 || liabilityStressBps > 50_000) revert BadConfig();
        Scenario storage s = scenarios[id];
        s.liabilityStressBps = liabilityStressBps;
        s.fixedSystemCost1e18 = fixedCost1e18;
        s.enabled = enabled;
        emit ScenarioSet(id, liabilityStressBps, fixedCost1e18, enabled);
    }

    function setScenarioAsset(uint256 id, address token, uint16 priceStressBps, uint16 liquidityBps) external onlyOwner {
        if (id >= scenarios.length || token == address(0) || priceStressBps > 10_000 || liquidityBps > 10_000) revert BadConfig();
        scenarioAsset[id][token] = ScenarioAsset(priceStressBps, liquidityBps);
        emit ScenarioAssetSet(id, token, priceStressBps, liquidityBps);
    }

    function scenarioRiskValue1e18(address token, uint256 amount, uint8 decimals_, uint256 id) external view returns (uint256) {
        if (id >= scenarios.length || !scenarios[id].enabled) return 0;
        ScenarioAsset memory s = scenarioAsset[id][token];
        uint256 base = baseRiskValue1e18(token, amount, decimals_);
        return (((base * uint256(s.priceStressBps)) / 10_000) * uint256(s.liquidityBps)) / 10_000;
    }

    function scenarioInfo(uint256 id) external view returns (bytes32 name, uint16 liabilityStressBps, uint256 fixedCost1e18, bool enabled) {
        Scenario memory s = scenarios[id];
        return (s.name, s.liabilityStressBps, s.fixedSystemCost1e18, s.enabled);
    }

    function scenarioCount() external view returns (uint256) { return scenarios.length; }
}
