// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Stores transparent, bounded QE inventory-sale windows.
/// @dev The pool never transfers reserves and may only be consumed by the
/// authorized settlement router. A window sells self-issued base inventory for
/// an external quote asset at a time-decaying oracle discount.
contract QEOpportunityPool {
    uint256 public constant BPS = 10_000;
    uint16 public constant MAX_DISCOUNT_BPS = 3_000;
    uint16 public constant MAX_PROTOCOL_FEE_BPS = 1_000;
    uint64 public constant MAX_WINDOW_DURATION = 7 days;

    struct Window {
        address base;
        address quote;
        uint128 maxBaseAmount;
        uint128 usedBaseAmount;
        uint16 startDiscountBps;
        uint16 endDiscountBps;
        uint16 protocolFeeBps;
        uint64 startsAt;
        uint64 expiresAt;
        bool active;
    }

    address public immutable governor;
    address public router;
    uint256 public nextWindowId;
    mapping(uint256 => Window) private _windows;

    error Unauthorized();
    error InvalidWindow();
    error InactiveWindow();
    error VolumeExceeded();

    event RouterSet(address indexed router);
    event WindowCreated(
        uint256 indexed id,
        address indexed base,
        address indexed quote,
        uint256 maxBaseAmount,
        uint256 startDiscountBps,
        uint256 endDiscountBps,
        uint256 protocolFeeBps,
        uint256 startsAt,
        uint256 expiresAt
    );
    event WindowClosed(uint256 indexed id);
    event WindowConsumed(
        uint256 indexed id,
        address indexed solver,
        uint256 baseAmount,
        uint256 discountBps,
        uint256 remainingBaseAmount
    );

    constructor(address governor_) {
        if (governor_ == address(0)) revert InvalidWindow();
        governor = governor_;
    }

    modifier onlyGovernor() {
        if (msg.sender != governor) revert Unauthorized();
        _;
    }

    modifier onlyRouter() {
        if (msg.sender != router || router == address(0)) revert Unauthorized();
        _;
    }

    function setRouter(address router_) external onlyGovernor {
        if (router_ == address(0)) revert InvalidWindow();
        router = router_;
        emit RouterSet(router_);
    }

    function createWindow(Window calldata input) external onlyGovernor returns (uint256 id) {
        if (
            input.base == address(0) || input.quote == address(0) || input.base == input.quote
                || input.maxBaseAmount == 0 || input.usedBaseAmount != 0
                || input.startDiscountBps > MAX_DISCOUNT_BPS
                || input.endDiscountBps > input.startDiscountBps
                || input.protocolFeeBps > MAX_PROTOCOL_FEE_BPS
                || input.startsAt < block.timestamp || input.expiresAt <= input.startsAt
                || input.expiresAt - input.startsAt > MAX_WINDOW_DURATION || !input.active
        ) revert InvalidWindow();

        id = nextWindowId++;
        _windows[id] = input;
        emit WindowCreated(
            id,
            input.base,
            input.quote,
            input.maxBaseAmount,
            input.startDiscountBps,
            input.endDiscountBps,
            input.protocolFeeBps,
            input.startsAt,
            input.expiresAt
        );
    }

    function closeWindow(uint256 id) external onlyGovernor {
        Window storage w = _windows[id];
        if (!w.active) revert InactiveWindow();
        w.active = false;
        emit WindowClosed(id);
    }

    function getWindow(uint256 id) external view returns (Window memory) {
        return _windows[id];
    }

    function currentDiscountBps(uint256 id) public view returns (uint256) {
        Window memory w = _windows[id];
        if (!w.active || block.timestamp < w.startsAt || block.timestamp > w.expiresAt) {
            revert InactiveWindow();
        }
        if (block.timestamp == w.startsAt || w.startDiscountBps == w.endDiscountBps) {
            return w.startDiscountBps;
        }
        uint256 elapsed = block.timestamp - w.startsAt;
        uint256 duration = w.expiresAt - w.startsAt;
        uint256 decay = uint256(w.startDiscountBps - w.endDiscountBps) * elapsed / duration;
        return uint256(w.startDiscountBps) - decay;
    }

    function consume(uint256 id, address solver, uint256 baseAmount)
        external
        onlyRouter
        returns (Window memory window, uint256 discountBps)
    {
        if (solver == address(0) || baseAmount == 0 || baseAmount > type(uint128).max) {
            revert InvalidWindow();
        }
        Window storage w = _windows[id];
        if (!w.active || block.timestamp < w.startsAt || block.timestamp > w.expiresAt) {
            revert InactiveWindow();
        }
        uint256 nextUsed = uint256(w.usedBaseAmount) + baseAmount;
        if (nextUsed > w.maxBaseAmount) revert VolumeExceeded();

        discountBps = currentDiscountBps(id);
        w.usedBaseAmount = uint128(nextUsed);
        if (nextUsed == w.maxBaseAmount) w.active = false;
        window = w;

        emit WindowConsumed(id, solver, baseAmount, discountBps, uint256(w.maxBaseAmount) - nextUsed);
    }
}
