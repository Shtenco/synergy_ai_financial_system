// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

/// @notice Semi-trusted MVP bridge vault for CORE.
/// Production version should replace the relayer with validator/light-client verification.
contract BridgeVault {
    using SafeTransferLib for address;

    address public immutable core;
    address public owner;
    mapping(address => bool) public relayer;
    mapping(bytes32 => bool) public processed;

    uint256 public epochLength = 1 hours;
    uint256 public maxReleasePerEpoch;
    uint256 public epochStart;
    uint256 public releasedThisEpoch;

    event Locked(bytes32 indexed transferId, address indexed from, uint256 amount, uint32 dstChain, bytes32 recipient);
    event Released(bytes32 indexed transferId, address indexed to, uint256 amount);
    event RelayerSet(address indexed relayer, bool allowed);
    event ReleaseCapSet(uint256 cap);

    error Unauthorized();
    error BadConfig();
    error Replay();
    error ReleaseCap();

    constructor(address core_, address owner_, uint256 maxReleasePerEpoch_) {
        if (core_ == address(0) || owner_ == address(0)) revert BadConfig();
        core = core_;
        owner = owner_;
        maxReleasePerEpoch = maxReleasePerEpoch_;
        epochStart = block.timestamp;
    }

    modifier onlyOwner(){ if(msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyRelayer(){ if(!relayer[msg.sender]) revert Unauthorized(); _; }

    function setRelayer(address who, bool allowed) external onlyOwner {
        relayer[who] = allowed;
        emit RelayerSet(who, allowed);
    }

    function setMaxReleasePerEpoch(uint256 cap) external onlyOwner {
        maxReleasePerEpoch = cap;
        emit ReleaseCapSet(cap);
    }

    function lockForBridge(uint256 amount, uint32 dstChain, bytes32 recipient)
        external returns (bytes32 transferId)
    {
        if (amount == 0 || recipient == bytes32(0)) revert BadConfig();
        core.safeTransferFrom(msg.sender, address(this), amount);
        transferId = keccak256(abi.encode(block.chainid, msg.sender, amount, dstChain, recipient, block.number));
        emit Locked(transferId, msg.sender, amount, dstChain, recipient);
    }

    function release(bytes32 transferId, address to, uint256 amount) external onlyRelayer {
        if (processed[transferId]) revert Replay();
        if (to == address(0) || amount == 0) revert BadConfig();
        _rollEpoch();
        if (maxReleasePerEpoch != 0 && releasedThisEpoch + amount > maxReleasePerEpoch) revert ReleaseCap();
        processed[transferId] = true;
        releasedThisEpoch += amount;
        core.safeTransfer(to, amount);
        emit Released(transferId, to, amount);
    }

    function _rollEpoch() private {
        if (block.timestamp >= epochStart + epochLength) {
            epochStart = block.timestamp;
            releasedThisEpoch = 0;
        }
    }
}
