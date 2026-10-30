from __future__ import annotations
import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
SEED = 42
FIELDNAMES = ['event_id', 'customer_id', 'customer_name', 'city', 'event_timestamp', 'source_sequence']
FIRST_NAMES = ['Aarav', 'Bhavya', 'Chetan', 'Divya', 'Esha', 'Farhan', 'Gita', 'Harish', 'Isha', 'Jay', 'Kavya', 'Lakshmi', 'Mohan', 'Nita', 'Om', 'Priya', 'Ravi', 'Sunita', 'Tarun', 'Uma', 'Vikram', 'Waqar', 'Xavier', 'Yasmin', 'Zara']
LAST_NAMES = ['Sharma', 'Patel', 'Reddy', 'Iyer', 'Nair', 'Mehta', 'Joshi', 'Kumar', 'Singh', 'Gupta', 'Das', 'Rao', 'Verma', 'Malhotra', 'Chopra']
CITIES = ['Mumbai', 'Delhi', 'Bangalore', 'Chennai', 'Hyderabad', 'Kolkata', 'Pune', 'Ahmedabad', 'Jaipur', 'Lucknow', 'Surat', 'Chandigarh', 'Bhopal', 'Nagpur', 'Indore']
BAD_TIMESTAMPS = ['2023-13-01T00:00:00Z', 'not-a-timestamp', '01/15/2023', '', 'yesterday']
BASE_DT = datetime(2020, 1, 1, tzinfo=timezone.utc)
END_DT = datetime(2025, 12, 31, tzinfo=timezone.utc)

def rand_name(rng: random.Random) -> str:
    return f'{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}'

def rand_dt(rng: random.Random, start: datetime=BASE_DT, end: datetime=END_DT) -> datetime:
    delta_secs = int((end - start).total_seconds())
    if delta_secs <= 0:
        return start
    return start + timedelta(seconds=rng.randint(0, delta_secs))

def fmt_dt(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%S+00:00')

def event_id(rng: random.Random) -> str:
    return f'E{rng.randint(100000, 999999)}'

def generate(num_rows: int, seed: int, output_path: Path, num_customers: int | None=None) -> None:
    rng = random.Random(seed)
    if num_customers is None:
        num_customers = max(10, num_rows // 10)
    cids = [f'C{i:06d}' for i in range(1, num_customers + 1)]
    cnames = {cid: rand_name(rng) for cid in cids}
    rows: list[dict] = []
    seq = 1
    last_ts: dict[str, datetime] = {}
    customer_events: dict[str, list[dict]] = {cid: [] for cid in cids}
    for cid in cids:
        ts = rand_dt(rng, BASE_DT, datetime(2021, 12, 31, tzinfo=timezone.utc))
        row = {'event_id': event_id(rng), 'customer_id': cid, 'customer_name': cnames[cid], 'city': rng.choice(CITIES), 'event_timestamp': fmt_dt(ts), 'source_sequence': seq}
        seq += 1
        rows.append(row)
        customer_events[cid].append(row)
        last_ts[cid] = ts
    remaining = num_rows - len(rows)
    for _ in range(remaining):
        cid = rng.choice(cids)
        roll = rng.random()
        if roll < 0.58:
            new_ts = rand_dt(rng, last_ts[cid] + timedelta(days=1), END_DT)
            row = {'event_id': event_id(rng), 'customer_id': cid, 'customer_name': cnames[cid], 'city': rng.choice(CITIES), 'event_timestamp': fmt_dt(new_ts), 'source_sequence': seq}
            seq += 1
            rows.append(row)
            customer_events[cid].append(row)
            last_ts[cid] = new_ts
        elif roll < 0.72:
            if customer_events[cid]:
                orig = rng.choice(customer_events[cid])
                dup = dict(orig)
                dup['source_sequence'] = seq
                seq += 1
                rows.append(dup)
        elif roll < 0.83:
            fault = rng.choice(['bad_ts', 'missing_cid', 'missing_name', 'missing_city'])
            row = {'event_id': event_id(rng), 'customer_id': cid, 'customer_name': cnames[cid], 'city': rng.choice(CITIES), 'event_timestamp': fmt_dt(rand_dt(rng)), 'source_sequence': seq}
            seq += 1
            if fault == 'bad_ts':
                row['event_timestamp'] = rng.choice(BAD_TIMESTAMPS)
            elif fault == 'missing_cid':
                row['customer_id'] = ''
            elif fault == 'missing_name':
                row['customer_name'] = ''
            elif fault == 'missing_city':
                row['city'] = ''
            rows.append(row)
        elif roll < 0.92:
            if last_ts[cid] > BASE_DT + timedelta(days=30):
                late_ts = rand_dt(rng, BASE_DT, last_ts[cid] - timedelta(days=1))
                row = {'event_id': event_id(rng), 'customer_id': cid, 'customer_name': cnames[cid], 'city': rng.choice(CITIES), 'event_timestamp': fmt_dt(late_ts), 'source_sequence': seq}
                seq += 1
                rows.append(row)
            else:
                new_ts = rand_dt(rng, last_ts[cid], END_DT)
                row = {'event_id': event_id(rng), 'customer_id': cid, 'customer_name': cnames[cid], 'city': rng.choice(CITIES), 'event_timestamp': fmt_dt(new_ts), 'source_sequence': seq}
                seq += 1
                rows.append(row)
        else:
            conflict_ts = last_ts[cid]
            row = {'event_id': event_id(rng), 'customer_id': cid, 'customer_name': cnames[cid], 'city': rng.choice(CITIES), 'event_timestamp': fmt_dt(conflict_ts), 'source_sequence': seq}
            seq += 1
            rows.append(row)
    rng.shuffle(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    malformed = sum((1 for r in rows if not r.get('customer_id') or not r.get('customer_name') or (not r.get('city')) or ('T' not in r.get('event_timestamp', ''))))
    print(f'Generated {len(rows):,} rows -> {output_path}')
    print(f'  Customers   : {num_customers:,}')
    print(f'  ~Malformed  : {malformed:,} rows ({malformed / len(rows) * 100:.1f}%)')
    print(f'  Seed        : {seed}')

def main() -> None:
    parser = argparse.ArgumentParser(description='Generate synthetic ChronoLedger input data')
    parser.add_argument('--rows', type=int, default=1000, help='Total rows to generate (default: 1000)')
    parser.add_argument('--output', type=Path, default=Path('data/generated/events.csv'), help='Output CSV path (default: data/generated/events.csv)')
    parser.add_argument('--seed', type=int, default=SEED, help=f'Random seed (default: {SEED})')
    parser.add_argument('--customers', type=int, default=None, help='Number of distinct customers (default: rows // 10)')
    args = parser.parse_args()
    if args.rows < 1:
        print('ERROR: --rows must be >= 1', file=sys.stderr)
        sys.exit(1)
    generate(num_rows=args.rows, seed=args.seed, output_path=args.output, num_customers=args.customers)
if __name__ == '__main__':
    main()
