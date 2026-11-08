import argparse, csv, io, logging, os, random
from datetime import date, timedelta
import psycopg, requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DB=os.getenv("DATABASE_URL","postgresql://portfolio:portfolio@localhost:5433/rates_weather")
WEATHER="https://archive-api.open-meteo.com/v1/archive"

def synthetic_fx(start,end):
    rows=[]; day=start
    while day<=end:
        for currency,rate in {"USD":129.5,"EUR":140.2,"GBP":163.8}.items():
            rows.append((day,currency,rate+(day.toordinal()%13)*0.07,"synthetic-demo",True))
        day+=timedelta(days=1)
    return rows

def fetch_fx(start,end):
    url=os.getenv("CBK_CSV_URL","").strip()
    if not url:
        logging.warning("CBK_CSV_URL missing: using labelled synthetic FX data")
        return synthetic_fx(start,end)
    response=requests.get(url,timeout=30); response.raise_for_status()
    result=[]
    for row in csv.DictReader(io.StringIO(response.text)):
        d=date.fromisoformat(row["date"])
        if start<=d<=end:
            result.append((d,row["currency"].upper(),float(row["rate"]),"configured-cbk-csv",False))
    return result

def fetch_weather(start,end):
    locations=[("Nairobi",-1.2864,36.8172),("Kisumu",-0.0917,34.7680),("Mombasa",-4.0435,39.6682)]
    rows=[]
    for name,lat,lon in locations:
        params={"latitude":lat,"longitude":lon,"start_date":start.isoformat(),"end_date":end.isoformat(),
          "daily":"temperature_2m_max,temperature_2m_min,precipitation_sum","timezone":"Africa/Nairobi"}
        try:
            data=requests.get(WEATHER,params=params,timeout=25); data.raise_for_status()
            daily=data.json()["daily"]
            rows.extend([(date.fromisoformat(d),name,daily["temperature_2m_max"][i],daily["temperature_2m_min"][i],
                          daily["precipitation_sum"][i],"open-meteo",False) for i,d in enumerate(daily["time"])])
        except Exception as exc:
            logging.exception("Weather fetch failed for %s: %s",name,exc)
            rng=random.Random(name+start.isoformat()); day=start
            while day<=end:
                low=15+rng.random()*7
                rows.append((day,name,round(low+7,1),round(low,1),round(rng.random()*10,1),"synthetic-fallback",True))
                day+=timedelta(days=1)
    return rows

def run(start,end):
    if start>end: raise ValueError("start must not be after end")
    with psycopg.connect(DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_fx_rates(
          observation_date date,currency text,kes_per_unit numeric,source text,is_synthetic boolean,
          PRIMARY KEY(observation_date,currency))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_weather(
          observation_date date,location text,temp_max_c numeric,temp_min_c numeric,precipitation_mm numeric,
          source text,is_synthetic boolean,PRIMARY KEY(observation_date,location))""")
        conn.executemany("""INSERT INTO daily_fx_rates VALUES(%s,%s,%s,%s,%s)
          ON CONFLICT(observation_date,currency) DO UPDATE SET kes_per_unit=excluded.kes_per_unit,
          source=excluded.source,is_synthetic=excluded.is_synthetic""",fetch_fx(start,end))
        conn.executemany("""INSERT INTO daily_weather VALUES(%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(observation_date,location) DO UPDATE SET temp_max_c=excluded.temp_max_c,
          temp_min_c=excluded.temp_min_c,precipitation_mm=excluded.precipitation_mm,
          source=excluded.source,is_synthetic=excluded.is_synthetic""",fetch_weather(start,end))
    logging.info("Completed ETL for %s to %s",start,end)

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--start",type=date.fromisoformat); ap.add_argument("--end",type=date.fromisoformat)
    ap.add_argument("--days",type=int,default=3); a=ap.parse_args()
    end=a.end or date.today()-timedelta(days=1); start=a.start or end-timedelta(days=a.days-1)
    run(start,end)
