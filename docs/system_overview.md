# ALA System Overview

## What this system does

The Autonomous Life-Cycle Arbitrator automates the retirement
decision for EV batteries — choosing between second-life reuse
and recycling automatically, fairly, and in compliance with EU law.

## Five innovations

1. Dynamic operational carbon tracking per charging session
2. Automated multi-party bid arbitration
3. Composite Circular Score — 4 criteria simultaneously
4. Privacy-preserving SHA-256 safety certificates
5. Hash-chain integrity linking passport to arbitration events

## How to run it

1. pip install -r requirements.txt
2. Copy config/config_example.py to config/config.py
3. Add your Electricity Maps API key to config/config.py
4. Open notebooks/eu_battery_passport.ipynb in Jupyter
5. Run all cells in order from Cell 1 to Cell 11

## Standards

- DIN DKE SPEC 99100 v1.3
- CEN/CENELEC JTC 24
- EU Battery Regulation 2023/1542
- SHA-256 FIPS 180-4
- IEC 62660-1