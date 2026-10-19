#!/usr/bin/env python3
"""Download completed NBA regular-season player boxscores from ESPN public endpoints.
ESPN's undocumented response schema can change; failures do not overwrite existing data.
"""
import csv
import datetime as dt
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

OUT=Path('data/nba-game-logs.csv')
COLUMNS=['player','date','points','rebounds','assists','threes','team','opponent','minutes','season','event_id','athlete_id']
BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'

def get_json(url):
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; SportsEdgeStats/1.0)','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=25) as resp:return json.load(resp)
        except Exception:
            if attempt==2:raise
            time.sleep(1.5*(attempt+1))

def scoreboard(day):
    d=get_json(BASE+'scoreboard?dates='+day.strftime('%Y%m%d')+'&limit=30')
    ids=[]
    for e in d.get('events',[]):
        season=e.get('season',{})
        if str(season.get('type',''))!='2':continue  # Regular season only
        if not e.get('status',{}).get('type',{}).get('completed'):continue
        ids.append(str(e['id']))
    return ids

def parse_event(event_id):
    d=get_json(BASE+'summary?event='+event_id)
    event=d.get('header',{}).get('competitions',[{}])[0]
    event_date=event.get('date') or d.get('header',{}).get('competitions',[{}])[0].get('date','')
    date=event_date[:10]
    if not date:raise ValueError('Missing event date '+event_id)
    season=str(d.get('header',{}).get('season',{}).get('year') or date[:4])
    teams={str(t.get('team',{}).get('id')):t.get('team',{}).get('abbreviation','') for t in event.get('competitors',[])}
    out=[]
    for side in d.get('boxscore',{}).get('players',[]):
        team=side.get('team',{}).get('abbreviation','')
        opponent=next((v for v in teams.values() if v and v!=team),'')
        for group in side.get('statistics',[]):
            labels=[str(x).upper() for x in group.get('labels',[])]
            for athlete in group.get('athletes',[]):
                if athlete.get('didNotPlay') or athlete.get('inactive'):continue
                vals=athlete.get('stats') or []
                if len(vals)!=len(labels):continue
                stats=dict(zip(labels,vals))
                if not all(k in stats for k in ('PTS','REB','AST')):continue
                player=athlete.get('athlete',{})
                name=player.get('displayName','')
                if not name:continue
                try:
                    points=float(stats['PTS']);rebounds=float(stats['REB']);assists=float(stats['AST'])
                    threes=float(str(stats.get('3PT','0-0')).split('-')[0])
                except (ValueError,TypeError):continue
                rawmin=str(stats.get('MIN',''))
                try:
                    minutes=round(float(rawmin.split(':')[0])+float(rawmin.split(':')[1])/60,2) if ':' in rawmin else float(rawmin)
                except ValueError:minutes=''
                if minutes==0:continue
                out.append(dict(player=name,date=date,points=points,rebounds=rebounds,assists=assists,threes=threes,team=team,opponent=opponent,minutes=minutes,season=season,event_id=event_id,athlete_id=player.get('id','')))
    return out

def main():
    today=dt.date.today()
    old=[]
    if OUT.exists():
        with OUT.open(newline='',encoding='utf-8') as f:old=list(csv.DictReader(f))
    # First run: recent stretch of previous regular season + start of current season.
    # Subsequent runs: past 3 days to catch corrections and newly completed games.
    if old:
        dates=[today-dt.timedelta(days=n) for n in range(4)]
    else:
        previous=[dt.date(2026,3,1)+dt.timedelta(days=n) for n in range(46)]
        current=[dt.date(2026,10,1)+dt.timedelta(days=n) for n in range(max(0,(today-dt.date(2026,10,1)).days+1))]
        dates=[x for x in previous+current if x<=today]
    print('Checking',len(dates),'NBA dates')
    ids=set();errors=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(scoreboard,d):d for d in dates}
        for f in as_completed(futures):
            try:ids.update(f.result())
            except Exception as e:errors.append(f'{futures[f]}: {e}')
    print('Completed regular-season games:',len(ids),'scoreboard errors:',len(errors))
    existing_events={str(r.get('event_id','')) for r in old}
    new_ids=sorted(ids-existing_events)
    new=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(parse_event,event_id):event_id for event_id in new_ids}
        for f in as_completed(futures):
            try:new.extend(f.result())
            except Exception as e:errors.append(f'event {futures[f]}: {e}')
    print('New player-game rows:',len(new),'errors:',len(errors))
    if errors:print('Sample errors:',*errors[:5],sep='\n')
    if not old and not new:raise SystemExit('No NBA player-game rows retrieved; refusing to publish an empty file')
    merged={((r.get('event_id') or r.get('date','')),(r.get('athlete_id') or r.get('player',''))):r for r in old+new}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=COLUMNS,extrasaction='ignore');w.writeheader();w.writerows(sorted(merged.values(),key=lambda r:(r['date'],r['player'])))
    print('Saved',len(merged),'rows to',OUT)

if __name__=='__main__':main()
