// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Minimal N-of-M timelocked controller with an independent pause guardian.
contract TimelockedMultisig {
    uint64 public constant MIN_DELAY = 24 hours;
    mapping(address => bool) public owners;
    uint256 public immutable threshold;
    address public immutable guardian;
    bool public paused;
    mapping(bytes32 => mapping(address => bool)) public approved;
    mapping(bytes32 => uint256) public approvalCount;
    mapping(bytes32 => uint64) public executableAt;
    mapping(bytes32 => bool) public executed;

    error Unauthorized();
    error NotReady();
    event Approved(bytes32 indexed id, address indexed owner);
    event Scheduled(bytes32 indexed id, uint64 executableAt);
    event Executed(bytes32 indexed id);
    event Paused(bool paused);

    constructor(address[] memory owners_, uint256 threshold_, address guardian_) {
        require(guardian_ != address(0) && threshold_ > 0 && threshold_ <= owners_.length);
        guardian = guardian_;
        threshold = threshold_;
        for (uint256 i; i < owners_.length; ++i) {
            require(owners_[i] != address(0) && !owners[owners_[i]]);
            owners[owners_[i]] = true;
        }
    }

    function idFor(address target, uint256 value, bytes calldata data, bytes32 salt) public view returns (bytes32) {
        return keccak256(abi.encode(block.chainid, address(this), target, value, keccak256(data), salt));
    }

    function approve(bytes32 id) external {
        if (!owners[msg.sender] || approved[id][msg.sender]) revert Unauthorized();
        approved[id][msg.sender] = true;
        ++approvalCount[id];
        emit Approved(id, msg.sender);
    }

    function schedule(bytes32 id) external {
        if (!owners[msg.sender] || approvalCount[id] < threshold || executableAt[id] != 0) revert Unauthorized();
        executableAt[id] = uint64(block.timestamp + MIN_DELAY);
        emit Scheduled(id, executableAt[id]);
    }

    function execute(address target, uint256 value, bytes calldata data, bytes32 salt) external payable returns (bytes memory result) {
        bytes32 id = idFor(target, value, data, salt);
        if (paused || executed[id] || executableAt[id] == 0 || block.timestamp < executableAt[id]) revert NotReady();
        executed[id] = true;
        (bool ok, bytes memory output) = target.call{value: value}(data);
        require(ok, "multisig call failed");
        emit Executed(id);
        return output;
    }

    function setPaused(bool next) external {
        if ((next && msg.sender != guardian) || (!next && msg.sender != address(this))) revert Unauthorized();
        paused = next;
        emit Paused(next);
    }

    receive() external payable {}
}
