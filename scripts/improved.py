#!/usr/bin/env python

import re
import pandas as pd
import requests
import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine
import logging
from datetime import datetime, timedelta
import os

class LegislatorsProcessor:
    def __init__(self, existing_members_url, db_params):
        self.existing_members_url = existing_members_url
        self.db_params = db_params
        self.logger = logging.getLogger(__name__)
        self.state_abbr_to_name = {
            'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
            'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
            'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
            'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
            'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
            'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
            'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
            'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
            'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
            'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming'
        }

    def fetch_legislators_data(self):
        try:
            existing_member_req = requests.get(self.existing_members_url)
            existing_member_req.raise_for_status()
            existing_members = existing_member_req.json()
            return existing_members
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching legislators data: {e}")
            return []

    def process_legislators(self, data):
        regex = re.compile('[^a-zA-Z\s]')
        house_dicts = []
        senate_dicts = []

        for member in data:
            terms = member.get('terms', [])
            if not terms:
                continue

            terms.sort(key=lambda x: x.get('end', ''), reverse=True)
            latest_term = terms[0]

            firstname = regex.sub('', member['name']['first'])
            lastname = regex.sub('', member['name']['last'])

            legislator_dict = {
                'firstname': firstname,
                'lastname': lastname,
                'id': member['id']['bioguide'],
                'party': latest_term.get('party'),
                'state': self.state_abbr_to_name.get(latest_term.get('state'), ''),
                'position': latest_term.get('type'),
                'start_term': latest_term.get('start'),
                'end_term': latest_term.get('end')
            }

            if 'official_full' in member['name']:
                legislator_dict['fullname'] = regex.sub('', member['name']['official_full'])
            else:
                legislator_dict['fullname'] = f"{firstname} {lastname}"

            if latest_term.get('type') == 'rep':
                house_dicts.append(legislator_dict)
            elif latest_term.get('type') == 'sen':
                senate_dicts.append(legislator_dict)

        return pd.DataFrame(house_dicts), pd.DataFrame(senate_dicts)

    def create_tables(self, conn):
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS house (
                        fullname TEXT,
                        firstname TEXT,
                        lastname TEXT,
                        id TEXT PRIMARY KEY,
                        party TEXT,
                        state TEXT,
                        position TEXT,
                        start_term TEXT,
                        end_term TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS senate (
                        fullname TEXT,
                        firstname TEXT,
                        lastname TEXT,
                        id TEXT PRIMARY KEY,
                        party TEXT,
                        state TEXT,
                        position TEXT,
                        start_term TEXT,
                        end_term TEXT
                    )
                ''')
            conn.commit()
            self.logger.info("Tables created successfully")
        except psycopg2.Error as e:
            self.logger.error(f"Error creating tables: {e}")
            conn.rollback()
            raise

    def fetch_existing_data(self, engine, table_name):
        try:
            query = f"SELECT * FROM {table_name}"
            existing_data = pd.read_sql_query(query, engine)
            return existing_data
        except pd.io.sql.DatabaseError as e:
            self.logger.error(f"Error fetching existing data from {table_name}: {e}")
            return pd.DataFrame()

    def update_table(self, conn, table_name, new_data):
        try:
            existing_data = self.fetch_existing_data(conn, table_name)

            # Find new members to insert
            new_members = new_data[~new_data['id'].isin(existing_data['id'])]

            # Find existing members to update
            existing_members = new_data[new_data['id'].isin(existing_data['id'])]

            with conn.cursor() as cursor:
                # Insert new members
                if not new_members.empty:
                    insert_query = f"""
                        INSERT INTO {table_name} (fullname, firstname, lastname, id, party, state, position, start_term, end_term)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    new_members_tuples = [tuple(x) for x in new_members.to_numpy()]
                    cursor.executemany(insert_query, new_members_tuples)

                # Update existing members
                if not existing_members.empty:
                    update_query = f"""
                        UPDATE {table_name}
                        SET fullname = %s,
                            firstname = %s,
                            lastname = %s,
                            party = %s,
                            state = %s,
                            position = %s,
                            start_term = %s,
                            end_term = %s
                        WHERE id = %s
                    """
                    existing_members_tuples = [
                        (row['fullname'], row['firstname'], row['lastname'], row['party'], row['state'], row['position'], row['start_term'], row['end_term'], row['id'])
                        for _, row in existing_members.iterrows()
                    ]
                    cursor.executemany(update_query, existing_members_tuples)

            conn.commit()
            self.logger.info(f"{table_name} table updated successfully")
        except (psycopg2.Error, pd.io.sql.DatabaseError) as e:
            self.logger.error(f"Error updating {table_name} table: {e}")
            conn.rollback()

    def weekly_update(self):
        try:
            conn = psycopg2.connect(**self.db_params)

            # Check if the "house" and "senate" tables exist
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'house'
                    )
                """)
                house_table_exists = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'senate'
                    )
                """)
                senate_table_exists = cursor.fetchone()[0]

            if not house_table_exists or not senate_table_exists:
                self.create_tables(conn)

            house_data, senate_data = self.process_legislators(self.fetch_legislators_data())
            self.update_table(conn, 'house', house_data)
            self.update_table(conn, 'senate', senate_data)

            conn.commit()
            self.logger.info("Weekly update completed successfully")
        except psycopg2.Error as e:
            self.logger.error(f"Error during weekly update: {e}")
            conn.rollback()
        finally:
            if conn:
                conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    existing_members_url = "https://theunitedstates.io/congress-legislators/legislators-current.json"
    db_params = {
        "dbname": os.environ.get("POSTGRES_DB"),
        "user": os.environ.get("POSTGRES_USER"),
        "password": os.environ.get("POSTGRES_PASSWORD"),
        "host": os.environ.get("POSTGRES_HOST"),
        "port": os.environ.get("POSTGRES_PORT")
    }

    processor = LegislatorsProcessor(existing_members_url, db_params)
    processor.weekly_update()