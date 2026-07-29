// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IAggregatorV3Like {
    function decimals() external view returns (uint8);
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);
}

/// @notice Normalizes trusted price feeds to 1e18 quote units per one base unit
/// and rejects stale or materially inconsistent solver references.
contract OracleGuard {
    uint256 public constant BPS = 10_000;
    uint16 public constant MAX_ALLOWED_DEVIATION_BPS = 2_000;

    struct Market {
        address feed;
        uint32 maxAge;
        uint16 maxDeviationBps;
        bool inverse;
        bool enabled;
    }

    address public immutable governor;
    mapping(bytes32 => Market) public markets;

    error Unauthorized();
    error InvalidMarket();
    error InvalidPrice();
    error StalePrice();
    error ExcessiveDeviation(uint256 deviationBps, uint256 allowedBps);

    event MarketSet(
        address indexed base,
        address indexed quote,
        address indexed feed,
        uint256 maxAge,
        uint256 maxDeviationBps,
        bool inverse
    );

    constructor(address governor_) {
        if (governor_ == address(0)) revert InvalidMarket();
        governor = governor_;
    }

    function marketKey(address base, address quote) public pure returns (bytes32) {
        return keccak256(abi.encode(base, quote));
    }

    function setMarket(address base, address quote, Market calldata market) external {
        if (msg.sender != governor) revert Unauthorized();
        if (
            base == address(0) || quote == address(0) || base == quote || market.feed == address(0)
                || market.maxAge == 0 || market.maxDeviationBps > MAX_ALLOWED_DEVIATION_BPS
                || !market.enabled
        ) revert InvalidMarket();
        markets[marketKey(base, quote)] = market;
        emit MarketSet(base, quote, market.feed, market.maxAge, market.maxDeviationBps, market.inverse);
    }

    function disableMarket(address base, address quote) external {
        if (msg.sender != governor) revert Unauthorized();
        markets[marketKey(base, quote)].enabled = false;
    }

    function readPrice(address base, address quote) public view returns (uint256 priceX18, uint256 updatedAt) {
        Market memory market = markets[marketKey(base, quote)];
        if (!market.enabled || market.feed == address(0)) revert InvalidMarket();

        (uint80 roundId, int256 answer,, uint256 feedUpdatedAt, uint80 answeredInRound) =
            IAggregatorV3Like(market.feed).latestRoundData();
        if (answer <= 0 || feedUpdatedAt == 0 || answeredInRound < roundId) revert InvalidPrice();
        if (block.timestamp > feedUpdatedAt + market.maxAge) revert StalePrice();

        uint8 feedDecimals = IAggregatorV3Like(market.feed).decimals();
        if (feedDecimals > 36) revert InvalidPrice();
        uint256 unsignedAnswer = uint256(answer);
        if (feedDecimals < 18) {
            priceX18 = unsignedAnswer * (10 ** (18 - feedDecimals));
        } else if (feedDecimals > 18) {
            priceX18 = unsignedAnswer / (10 ** (feedDecimals - 18));
        } else {
            priceX18 = unsignedAnswer;
        }
        if (priceX18 == 0) revert InvalidPrice();
        if (market.inverse) priceX18 = 1e36 / priceX18;
        updatedAt = feedUpdatedAt;
    }

    function validateReference(address base, address quote, uint256 referencePriceX18)
        external
        view
        returns (uint256 oraclePriceX18, uint256 deviationBps)
    {
        if (referencePriceX18 == 0) revert InvalidPrice();
        (oraclePriceX18,) = readPrice(base, quote);
        uint256 diff = referencePriceX18 > oraclePriceX18
            ? referencePriceX18 - oraclePriceX18
            : oraclePriceX18 - referencePriceX18;
        deviationBps = diff * BPS / oraclePriceX18;
        uint256 allowed = markets[marketKey(base, quote)].maxDeviationBps;
        if (deviationBps > allowed) revert ExcessiveDeviation(deviationBps, allowed);
    }
}
