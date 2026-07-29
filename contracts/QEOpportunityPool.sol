// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Creates bounded QE trading windows. It never creates value itself.
/// External solvers compete for opportunities and pay protocol fees.
contract QEOpportunityPool {
    struct Window {
        address base;
        address quote;
        uint256 maxVolume;
        uint256 usedVolume;
        uint256 minSpreadBps;
        uint256 solverFeeBps;
        uint256 deadline;
        bool active;
    }

    address public immutable governor;
    uint256 public nextWindow;
    mapping(uint256 => Window) public windows;

    error Unauthorized();
    error Inactive();
    error VolumeExceeded();

    event WindowCreated(uint256 indexed id,address base,address quote,uint256 volume,uint256 fee);
    event Filled(uint256 indexed id,address solver,uint256 volume,uint256 fee);

    constructor(address governor_) { governor = governor_; }

    function createWindow(Window calldata w) external returns(uint256 id) {
        if(msg.sender!=governor) revert Unauthorized();
        id=nextWindow++;
        windows[id]=w;
        emit WindowCreated(id,w.base,w.quote,w.maxVolume,w.solverFeeBps);
    }

    function consume(uint256 id,uint256 volume) external returns(uint256 fee){
        Window storage w=windows[id];
        if(!w.active || block.timestamp>w.deadline) revert Inactive();
        if(w.usedVolume+volume>w.maxVolume) revert VolumeExceeded();
        w.usedVolume+=volume;
        fee=volume*w.solverFeeBps/10000;
        emit Filled(id,msg.sender,volume,fee);
    }
}
