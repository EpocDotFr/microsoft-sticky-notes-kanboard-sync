from watchdog.events import PatternMatchingEventHandler
from utils import debug, split_note_text
from urllib import parse
import rtf.Rtf2Markdown
import watchdog.events
import olefile
import sqlite3
import configparser
import kanboard


class FileHandlerInterface(PatternMatchingEventHandler):
    """Base class for all the Sticky Notes file handlers."""

    sync_engine = None

    def __init__(self, sync_engine, patterns=None):
        self.sync_engine = sync_engine

        super().__init__(ignore_directories=True, patterns=patterns)

    def is_valid_event(self, event):
        if self.sync_engine.sticky_notes_file_path != event.src_path:
            return False

        if event.event_type == watchdog.events.EVENT_TYPE_MODIFIED:
            return True
        elif event.event_type == watchdog.events.EVENT_TYPE_DELETED:
            debug(self.sync_engine.sticky_notes_file_path + ' was unexpectedly deleted', err=True, terminate=True)
        elif event.event_type == watchdog.events.EVENT_TYPE_MOVED:
            debug(self.sync_engine.sticky_notes_file_path + ' was unexpectedly moved to ' + event.dest_path, err=True,
                  terminate=True)
        else:
            debug('Unhandled event type: ' + event.event_type, err=True)
            return False

    def sync_note(self, note):
        note_title, note_text = split_note_text(note['text'])

        response = kanboard.create_task(title=note_title,
                                        description=note_text,
                                        color_id=note['color']
                                        )

    def on_any_event(self, event):
        if not self.is_valid_event(event):
            pass

        notes = self.get_notes()

        for note in notes:
            try:
                self.sync_note(note)
            except Exception as e:
                debug(e, err=True)

    def get_notes(self):
        """Must be overridden to return a list of notes regarding the filetype we are watching."""

        raise Exception('get_notes must be overridden')


class SNTFileHandler(FileHandlerInterface):
    """StickyNotes.snt file handler"""

    snt_file = None

    def __init__(self, sync_engine):
        if not olefile.isOleFile(sync_engine.sticky_notes_file_path):
            debug(sync_engine.sticky_notes_file_path + ' isn\'t a valid Sticky Notes file', err=True, terminate=True)

        super().__init__(patterns=['*.snt'], sync_engine=sync_engine)

    def get_notes(self):
        notes = []

        self.snt_file = olefile.OleFileIO(self.sync_engine.sticky_notes_file_path)

        for storage in self.snt_file.listdir(storages=True, streams=False):
            note_id = storage[0]  # UUID-like string representing the note ID
            note_text_rtf_file = '0'  # RTF content of the note

            note_text_rtf = ''

            with self.snt_file.openstream([note_id, note_text_rtf_file]) as note_content:
                note_text_rtf = note_content.read().decode()

            notes.append({'text': rtf.Rtf2Markdown.getMarkdown(note_text_rtf), 'color': None})

        self.snt_file.close()

        return notes


class SQLiteFileHandler(FileHandlerInterface):
    """plum.sqlite file handler"""

    colors_map = {
        'Yellow': 'yellow',
        'Green': 'green',
        'Blue': 'blue',
        'Purple': 'purple',
        'Pink': 'pink'
    }

    connection = None

    def __init__(self, sync_engine):
        super().__init__(patterns=['*.sqlite'], sync_engine=sync_engine)

    def get_notes(self):
        self.connection = sqlite3.connect('file:' + self.sync_engine.sticky_notes_file_path + '?mode=ro', uri=True)
        self.connection.row_factory = sqlite3.Row

        cursor = self.connection.cursor()
        notes_db = cursor.execute('SELECT Text, Theme FROM Note')

        notes = [{'text': rtf.Rtf2Markdown.getMarkdown(note['Text']), 'color': self.get_note_color(note['Theme'])} for note in notes_db]

        self.connection.close()

        return notes

    def get_note_color(self, note):
        return self.colors_map[note['color']] if note['color'] in self.colors_map else None


class INIFileHandler(FileHandlerInterface):
    """Settings.ini file handler"""

    sidebar_config = None

    def __init__(self, sync_engine):
        super().__init__(patterns=['*.ini'], sync_engine=sync_engine)

    def get_notes(self):
        notes = []

        self.sidebar_config = configparser.ConfigParser()
        self.sidebar_config.read(self.sync_engine.sticky_notes_file_path)

        notes_color = None

        for section in self.sidebar_config.sections():
            if not section.starts_with('Section '):
                continue

            if 'NoteCount' not in self.sidebar_config[section]:
                continue

            notes_color = self.sidebar_config[section]['ColorSaved'] if 'ColorSaved' in self.sidebar_config[section] and notes_color is None else None

            for key in self.sidebar_config[section]:
                if key.isdigit():
                    notes.append({'text': parse.unquote(self.sidebar_config[section][key]), 'color': notes_color})

            break

        return notes
