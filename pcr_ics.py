import argparse
import json
import logging
import shutil
import sqlite3
import uuid
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Union
import os
import sys

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
from ics.utils import arrow_to_iso, iso_to_arrow

__version__ = (1, 0, 0)

# Envirnments
cn_timezone = pytz.timezone('Asia/Shanghai')
now = cn_timezone.localize(datetime.now())
CN_SERVER_RELEASED_TIME = cn_timezone.localize(datetime(2020, 4, 17, 11))


BASE_URL = 'https://redive.estertion.win'
CN_VERSION_URL = f'{BASE_URL}/last_version_cn.json'
CN_DATABASE_URL = f'{BASE_URL}/db/redive_cn.db.br'
DEPLOY_URL = 'https://wlkz.github.io/pcr_ics/dist/pcr_cn.ics'

IS_GITHUB_ACTIONS = not os.environ.get('GITHUB_WORKFLOW') is None


# Logger setting
def setup_logger(
    name=None,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    filepath=None,
    distributed_rank=0,
) -> logging.Logger:
    """Setups logger: name, level, format etc.
    (From ignite utils)

    Args:
        name (str, optional): new name for the logger. If None, the standard logger is used.
        level (int): logging level, e.g. CRITICAL, ERROR, WARNING, INFO, DEBUG
        format (str): logging format. By default, `%(asctime)s %(name)s %(levelname)s: %(message)s`
        filepath (str, optional): Optional logging file path. If not None, logs are written to the file.
        distributed_rank (int, optional): Optional, rank in distributed configuration to avoid logger setup for workers.
        If None, distributed_rank is initialized to the rank of process.

    Returns:
        logging.Logger

    For example, to improve logs readability when training with a trainer and evaluator:

    .. code-block:: python

        from ignite.utils import setup_logger

        trainer = ...
        evaluator = ...

        trainer.logger = setup_logger("trainer")
        evaluator.logger = setup_logger("evaluator")

        trainer.run(data, max_epochs=10)

        # Logs will look like
        # 2020-01-21 12:46:07,356 trainer INFO: Engine run starting with max_epochs=5.
        # 2020-01-21 12:46:07,358 trainer INFO: Epoch[1] Complete. Time taken: 00:5:23
        # 2020-01-21 12:46:07,358 evaluator INFO: Engine run starting with max_epochs=1.
        # 2020-01-21 12:46:07,358 evaluator INFO: Epoch[1] Complete. Time taken: 00:01:02
        # ...

    """
    logger = logging.getLogger(name)

    # don't propagate to ancestors
    # the problem here is to attach handlers to loggers
    # should we provide a default configuration less open ?
    if name is not None:
        logger.propagate = False

    # Remove previous handlers
    if logger.hasHandlers():
        for h in list(logger.handlers):
            logger.removeHandler(h)

    formatter = logging.Formatter(format)

    if distributed_rank > 0:
        logger.addHandler(logging.NullHandler())
    else:
        logger.setLevel(level)

        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        if filepath is not None:
            fh = logging.FileHandler(filepath)
            fh.setLevel(level)
            fh.setFormatter(formatter)
            logger.addHandler(fh)

    return logger


LOGGER = setup_logger(Path(__file__).stem)

# python_ics hooks


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
    def parse_dtstamp(event, line):
        return

    def parse_created(event, line):
        if line:
            # get the dict of vtimezones passed to the classmethod
            tz_dict = event._classmethod_kwargs["tz"]
            event.created = iso_to_arrow(line, tz_dict)
    # def parse_created(event, line):
    #     if line:
    #         event.created = int(line.value)

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


def download(url, dst='.', name=None, decompress=False, sess=None):
    if not name:
        name = url.split('/')[-1]
    dst = Path(dst) / name

    if not sess:
        sess = requests.Session()

    res = sess.get(url, stream=True)
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


class Database:
    def __init__(self, sess=None):
        self.db_path = None
        self._latest_version = None

        self._con = None
        self._req_sess = sess or requests.Session()

    @property
    def latest_version(self):
        if self._latest_version:
            return self._latest_version

        version_meta = self._req_sess.get(CN_VERSION_URL).json()
        latest_version = version_meta['TruthVersion']

        self._latest_version = latest_version

        return latest_version

    def download_latest(self):
        db_path = download(CN_DATABASE_URL,
                           name=f'{self.latest_version}.db', decompress=True, sess=self._req_sess)
        self.db_path = db_path

    def unlink(self):
        self.db_path.unlink()

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

        start_time = cn_timezone.localize(
            datetime.strptime(start_time, '%Y/%m/%d %H:%M:%S'))
        end_time = cn_timezone.localize(
            datetime.strptime(end_time, '%Y/%m/%d %H:%M:%S'))

        event_name = self.get_event_name(row)
        uid = str(uuid_generator(self.get_url(rid)))

        return Event(event_name, start_time, end_time, uid=uid)

    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        return self._event_name


CONSTELLATIONS = [
    '水瓶', '双鱼', '白羊', '金牛', '双子', '巨蟹',
    '狮子', '处女', '天秤', '天蝎', '射手', '摩羯',
]
CONSTELLATION_OFFSET = 1


class ClanBattleQuery(Query):
    table_name = 'clan_battle_period'
    id_field = 'clan_battle_id'

    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        rid = row[0]
        clan_battle_id = rid - 1000
        constellation = CONSTELLATIONS[(
            clan_battle_id + CONSTELLATION_OFFSET) % 12]
        return f'第{clan_battle_id}期{constellation}座团队战'


class FreeGachaQuery(Query):
    table_name = 'campaign_freegacha'
    _event_name = '每日一次 免费十连活动'

    @property
    def query_str(self):
        return '''
        SELECT id, start_time, end_time, freegacha_1, freegacha_10
        FROM campaign_freegacha
        WHERE freegacha_10 == 1 OR freegacha_1 == 1
        '''

    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        freegacha_1, freegacha_10 = row[3:]
        assert freegacha_1 != freegacha_10
        if freegacha_1 == 1:
            return '每日一次 免费单抽活动'
        elif freegacha_10 == 1:
            return '每日一次 免费十连活动'
        else:
            raise NotImplementedError()


# 31, 41 「普通关卡」掉落量{}倍庆典
# 32, 42 「困难关卡」掉落量{}倍庆典
# 34, 44 「探索」掉落量{}倍庆典
# 37 「圣迹调查」掉落量2倍庆典
# 38 「神殿调查」掉落量2倍庆典
# 45 「地下城」玛那{}倍庆典
# 131, 141 「活动关卡」2倍庆典
# 132, 142 「活动关卡（HARD）」掉落量2倍庆典
# 151, 152  「活动关卡」 玩家经验值获得量1.5倍

campaign_category_to_repr = {
    31: '「普通关卡」掉落量{}倍庆典',
    32: '「困难关卡」掉落量{}倍庆典',
    37: '「圣迹调查」掉落量{}倍庆典',
    38: '「神殿调查」掉落量{}倍庆典',
    44: '「探索」掉落量{}倍庆典',
    45: '「地下城」玛那{}倍庆典',
    131: '「活动关卡（普通）」掉落量{}倍庆典',
    132: '「活动关卡（困难）」掉落量{}倍庆典',
    151: '「活动关卡」玩家经验值获得量{}倍',
    91: '大师币{}倍',
    39: 'VH图{}倍'
}


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

        if int(value) % 1000 != 0:
            ratio = f'{value / 1000:.1f}'
        else:
            ratio = f'{int(value / 1000)}'
        return campaign_category_repr.format(ratio)


class TowerQuery(Query):
    @property
    def query_str(self):
        return '''
        SELECT tower_schedule.tower_schedule_id, tower_schedule.start_time, tower_schedule.end_time, tower_area_data.max_floor_num
        FROM tower_schedule
        INNER JOIN tower_area_data
        ON tower_area_data.tower_area_id == tower_schedule.max_tower_area_id
        '''
    table_name = 'tower_schedule'
    id_field = 'tower_schedule_id'
    _event_name = '露娜之塔'

    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        max_floor_num = row[3]

        return f'{self._event_name} {max_floor_num}层'


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
        return f'剧情活动：{title}'

class CharaFortuneQuery(Query):
    table_name = 'chara_fortune_schedule'
    id_field = 'fortune_id'

    @property
    def query_str(self):
        return '''
        SELECT fortune_id, start_time, end_time, name
        FROM chara_fortune_schedule
        '''
    
    def iter_row(self, con):
        for row in super().iter_row(con):
            start_time, end_time = row[1:3]

            # polyfill for old version (calendar_db_version < 202101211454) chara_fortune_schedule time str
            if len(start_time.split()[1]) <= len("05:00"):
                # 2020/7/11 5:00 -> 2020/7/11 5:00:00
                start_time = f'{start_time}:00'
                # 2020/7/25 4:59 -> 2020/7/25 4:59:59
                end_time = f'{end_time}:59'

            yield row[0], start_time, end_time, row[3]
    
    def get_event_name(self, row: Union[sqlite3.Row, tuple]) -> str:
        name = row[3]
        # 第1届 兰德索尔杯
        return name


querys = [v() for name, v in globals().items()
          if name.endswith('Query') and name != 'Query']


def add_modified_message(event: Event):
    """add modified message to event
    """
    event.created = now
    event.last_modified = now
    event.sequence = 0


def update_event(old_event: Event, new_event: Event):
    """update if event is modified

    Args:
        old_event (Event): event loaded from last ics file
        new_event (Event): event loaded from latest database
    """
    new_event.created = old_event.created
    new_event.last_modified = old_event.last_modified
    new_event.sequence = old_event.sequence

    # if modified
    if new_event != old_event:
        new_event.last_modified = now
        new_event.sequence += 1


def create_new_calendar():
    c = Calendar()
    c.extra.append(ContentLine('METHOD', value='PUBLISH'))
    c.extra.append(ContentLine('X-WR-CALNAME', value='公主连接国服活动日历'))
    c.extra.append(ContentLine(
        'X-WR-CALDESC', value='公主连接国服活动日历，由pcr_ics（https://git.io/JLhLb）生成，数据来自干炸里脊资料站'))
    c.extra.append(ContentLine('X-WR-TIMEZONE', value='Asia/Shanghai'))
    c.extra.append(ContentLine('CALSCALE', value='GREGORIAN'))
    return c


DB_VERSION_KEY = 'X-PCR-ICS-DB-VERSION'


def generate_calendar(db, calendar):
    uid2events = {e.uid: e for e in calendar.events}

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

    calendar.events = set(uid2events.values())

    return calendar


class SortedSet(set):
    def __init__(self, iterable, key):
        super().__init__(iterable)
        self._key = key

    def __iter__(self):
        return iter(sorted(super().__iter__(), key=self._key))


def prettify_calendar(calendar):
    calendar.events = SortedSet(calendar.events, key=lambda x: (x.begin, x.end, x.name))
    calendar.extra.sort(key=lambda x: x.name)
    return calendar


def set_output(name, value):
    sys.stdout.write(f'::set-output name={name}::{value}\n')


def main(ref_calendar_path, target):
    # load created calendar
    LOGGER.info(f'pcr_ics start! version {__version__}')
    LOGGER.info(f'ref_calendar_path {ref_calendar_path}')

    target = Path(target)
    if target.exists():
        target.unlink()

    if ref_calendar_path != 'none':
        if ref_calendar_path.startswith('http'):
            try:
                res = requests.get(ref_calendar_path)
                res.encoding = 'utf-8'
                with open(target, 'wb') as fp:
                    fp.write(res.content)
            except requests.exceptions.RequestException as ex:
                LOGGER.error(f'request error when fetching ref_calendar')
                LOGGER.error(ex)
                raise ex
        else:
            ref_calendar_path = Path(ref_calendar_path)
            if ref_calendar_path.exists():
                shutil.copy(ref_calendar_path, target)

    if target.exists():
        with target.open('r', encoding='utf-8') as fp:
            calendar = Calendar(fp.read())
    else:
        calendar = create_new_calendar()

    # to make it simple, I parse db version by myself
    query_calendar_db_version_line = [
        cl for cl in calendar.extra if cl.name == DB_VERSION_KEY]
    if len(query_calendar_db_version_line) == 1:
        calendar_db_version_line = query_calendar_db_version_line[0]
    else:
        calendar_db_version_line = ContentLine(DB_VERSION_KEY)
        calendar.extra.append(calendar_db_version_line)
    calendar_db_version = calendar_db_version_line.value or None
    LOGGER.info(f'calendar_db_version {calendar_db_version}')

    # fetch db
    try:
        db = Database()
        if db.latest_version == calendar_db_version:
            LOGGER.info(f'calendar is up to date')
            if IS_GITHUB_ACTIONS:
                github_sha = os.environ.get('GITHUB_SHA')
                if github_sha:
                    sha_str = f'from {github_sha} '
                else:
                    sha_str = ''
                set_output('PCR_ICS_COMMIT',
                   f'deploy: triggered update {sha_str}(github_actions)'
                   )
            return
        db.download_latest()
    except requests.exceptions.RequestException as ex:
        LOGGER.error(f'request error when updating db')
        LOGGER.error(ex)
        raise ex

    calendar_db_version_line.value = db.latest_version

    calendar = generate_calendar(db, calendar)
    calendar = prettify_calendar(calendar)
    LOGGER.info(f'generate_calendar OK')
    with open(target, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(str(calendar))
    LOGGER.info(f'target {target} is saved!')

    if IS_GITHUB_ACTIONS:
        set_output('PCR_ICS_COMMIT',
                   f'deploy: bump ics file to version {db.latest_version} (github_actions)'
                   )


def get_argparser():
    parser = argparse.ArgumentParser(
        description='pcr_ics: A iCalendar generator for Princess Connect! Re:Dive (公主连结Re:Dive), based on 干炸里脊资源站.')
    parser.add_argument('--ref-calendar-path',
                        default=DEPLOY_URL, help='The reference ics file.')
    parser.add_argument(
        '--target', default='./deploy/dist/pcr_cn.ics', help='The ics output path.')

    return parser


if __name__ == "__main__":
    parser = get_argparser()
    opt = parser.parse_args()
    main(opt.ref_calendar_path, opt.target)
