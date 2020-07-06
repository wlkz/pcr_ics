import json
import shutil
import sqlite3
import uuid
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Union

import brotli
import pytz
import requests
from ics import Calendar as _Calendar
from ics import Event as _Event
from ics.grammar.parse import ContentLine
from ics.parsers.event_parser import EventParser as _EventParser
from ics.parsers.icalendar_parser import CalendarParser as _CalendarParser
from ics.parsers.parser import option
from ics.serializers.event_serializer import \
    EventSerializer as _EventSerializer
from ics.serializers.icalendar_serializer import CalendarSerializer
from ics.utils import arrow_to_iso

BASE_URL = 'https://redive.estertion.win'

CN_VERSION_URL = f'{BASE_URL}/last_version_cn.json'
CN_DATABASE_URL = f'{BASE_URL}/db/redive_cn.db.br'

cn_timezone =pytz.timezone('Asia/Shanghai')
now = cn_timezone.localize(datetime.now())
CN_SERVER_RELEASED_TIME = cn_timezone.localize(datetime(2020, 4, 17, 11))


class EventSerializer(_EventSerializer):
    def serialize_created(event, container):
        if event.created:
            container.append(ContentLine(
                "CREATED", value=arrow_to_iso(event.created)))

    def serialize_dtstamp(event, container):
        container.append(ContentLine("DTSTAMP", value=arrow_to_iso(now)))

    def serialize_sequence(event, container):
        if not event.sequence is None:
            container.append(ContentLine("SEQUENCE", value=event.sequence))


class EventParser(_EventParser):
    def parse_sequence(event, line):
        if line:
            event.sequence = int(line.value)


class CalendarParser(_CalendarParser):
    """hook CalendarParser to replace event builder to hooded version
    """
    @option(multiple=True)
    def parse_vevent(calendar, lines):
        # tz=calendar._timezones gives access to the event factory to the
        # timezones list
        def event_factory(x):
            return Event._from_container(x, tz=calendar._timezones)

        calendar.events = set(map(event_factory, lines))


class Calendar(_Calendar):
    class Meta:
        name = 'VCALENDAR'
        parser = CalendarParser
        serializer = CalendarSerializer


class Event(_Event):
    class Meta:
        name = "VEVENT"
        parser = EventParser
        serializer = EventSerializer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sequence = None


def download(url, dst='.', name=None, decompress=False):
    if not name:
        name = url.split('/')[-1]
    dst = Path(dst) / name
    res = requests.get(url, stream=True)
    decompresser = None
    if decompress:
        decompresser = brotli.Decompressor()
    with open(dst, 'wb') as fp:
        for chunk in res.iter_content(chunk_size=8192):
            if decompress:
                chunk = decompresser.decompress(chunk)
            fp.write(chunk)
    if decompress:
        decompresser.finish()
    return dst


DB_PATH = Path('./db')


class Database:
    def __init__(self):
        db_path = DB_PATH / 'cn.db'

        self.db_path = db_path
        self._con = None

    def update(self):
        latest_version_path = download(CN_VERSION_URL, DB_PATH)
        local_version_path = DB_PATH / 'local_version_cn.json'
        db_path = self.db_path
        if local_version_path.exists():
            with latest_version_path.open('r', encoding='utf-8') as fp:
                latest_version = json.load(fp)['TruthVersion']
            with local_version_path.open('r', encoding='utf-8') as fp:
                local_version = json.load(fp)['TruthVersion']
            # actually we does not need to know whether latest version is newer than local versino
            need_update = latest_version != local_version
        else:
            need_update = True

        if need_update:
            db_path = download(CN_DATABASE_URL, DB_PATH,
                               name='cn.db', decompress=True)
            self.db_path = db_path
        shutil.move(latest_version_path, local_version_path)

    def __enter__(self):
        if self._con is not None:
            raise RuntimeError('Already connected')
        self._con = sqlite3.connect(self.db_path)
        # self._con.row_factory = sqlite3.Row
        return self._con

    def __exit__(self, exc_ty, exc_val, tb):
        self._con.close()
        self._con = None


def uuid_generator(name):
    return uuid.uuid3(uuid.NAMESPACE_URL, name)


class Query:
    table_name = ''
    _event_name = ''
    id_field = 'id'

    @property
    def query_str(self):
        return f'''
        SELECT {self.id_field}, start_time, end_time
        FROM {self.table_name}
        '''

    def iter_row(self, con: Connection):
        return con.execute(self.query_str)

    def iter_event(self, con: Connection):
        for row in self.iter_row(con):
            yield self.event_builder(row)

    def get_url(self, rid):
        return f'pcr_cn/{self.table_name}/{rid}'

    def event_builder(self, row: Union[sqlite3.Row, tuple]):
        rid, start_time, end_time = row[:3]

        start_time =  cn_timezone.localize(datetime.strptime(start_time, '%Y/%m/%d %H:%M:%S'))
        end_time = cn_timezone.localize(datetime.strptime(end_time, '%Y/%m/%d %H:%M:%S'))

        event_name = self.get_event_name(row)
        uid = str(uuid_generator(self.get_url(rid)))

        return Event(event_name, start_time, end_time, uid=uid)

    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        return self._event_name


class ClanBattleQuery(Query):
    table_name = 'clan_battle_period'
    id_field = 'clan_battle_id'
    _event_name = '工会战'


class FreeGachaQuery(Query):
    table_name = 'campaign_freegacha'
    _event_name = '免费抽卡'


campaign_category_to_repr = {45: '地下城', 91: '大师币', 31: 'N图', 32: 'H图',
                             131: '活动N图', 132: '活动H图', 37: '圣迹', 38: '神殿', 44: '探索', 39: 'VH图'}


class CampaignQuery(Query):
    table_name = 'campaign_schedule'

    @property
    def query_str(self):
        return '''
        SELECT id, start_time, end_time, campaign_category, value
        FROM campaign_schedule
        '''

    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        campaign_category, value = row[3:]
        campaign_category_repr = campaign_category_to_repr.get(
            campaign_category, '')
        if campaign_category_repr == '':
            return 'skip'
        ratio = value / 1000
        return f'{campaign_category_repr} {ratio:.1f} 倍'


class TowerQuery(Query):
    table_name = 'tower_schedule'
    id_field = 'tower_schedule_id'
    _event_name = '露娜塔'


class HatsuneQuery(Query):
    table_name = 'hatsune_schedule'
    id_field = 'event_id'

    @property
    def query_str(self):
        return f'''
        SELECT a.{self.id_field}, a.start_time, a.end_time, b.title
        FROM hatsune_schedule AS a JOIN event_story_data AS b ON a.event_id = b.value
        '''

    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        title = row[3]
        return f'活动：{title}'


querys = [v() for name, v in globals().items()
          if name.endswith('Query') and name != 'Query']


def add_modified_message(event: Event):
    event.created = now
    event.last_modified = now
    event.sequence = 0


def update_event(old_event: Event, new_event: Event):
    new_event.created = old_event.created
    new_event.last_modified = old_event.last_modified
    new_event.sequence = old_event.sequence

    if new_event != old_event:
        new_event.last_modified = now
        new_event.sequence = old_event.sequence + 1


if __name__ == "__main__":
    calendar_path = Path('./dist') / 'pcr_cn.ics'
    if calendar_path.exists():
        with calendar_path.open('r', encoding='utf-8') as fp:
            c = Calendar(fp.read())
    else:
        c = Calendar()
        c.creator = 'wlkz. Powered by ics.py - http://git.io/lLljaA'
        c.extra.append(ContentLine('METHOD', value='PUBLISH'))
        c.extra.append(ContentLine('X-WR-CALNAME', value='公主连接国服活动日历'))
        c.extra.append(ContentLine(
            'X-WR-CALDESC', value='公主连接国服活动日历，数据来自干炸里脊资料站'))
    db = Database()
    # db.update()
    uid2events = {e.uid: e for e in c.events}
    with db as con:
        for q in querys:
            for e in q.iter_event(con):
                if e.name == 'skip' or e.end < CN_SERVER_RELEASED_TIME:
                    continue
                if e.begin < CN_SERVER_RELEASED_TIME:
                    e.begin = CN_SERVER_RELEASED_TIME
                old_event = uid2events.get(e.uid)
                if old_event:
                    update_event(old_event, e)
                else:
                    add_modified_message(e)
                uid2events[e.uid] = e

    c.events = set(uid2events.values())

    with open(calendar_path, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(str(c))
