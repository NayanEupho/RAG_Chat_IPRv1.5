# Example: Long Complex Answer (Fragmented)
## IT Operations
### Disaster Recovery Plan

**Q: Describe the step-by-step server restoration process.**
**A:** This process consists of multiple critical phases to ensure data integrity and minimal downtime:

1. **Detection Phase**: The monitoring system triggers an alert if servers are unreachable for > 3 minutes.
2. **Isolation Phase**: Infected or failing nodes are sequestered from the main network to prevent data corruption.
3. **Backup Selection**: The most recent valid snapshot (RPO < 1 hour) is selected from the immutable cloud storage.
4. **Provisioning**: New virtual instances are spun up in a different availability zone.
5. **Data Hydration**: The database logs are replayed against the snapshot to bring it up to the point of failure.
6. **Integrity Check**: Automated scripts verify the MD5 checksums of critical system files.
7. **Traffic Rerouting**: DNS records are updated to point to the new healthy instances.

Each step must be documented in the incident report log and signed off by the Shift Lead.
