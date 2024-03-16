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
        senate_dicts = []

        for member in data:
            terms = member.get('terms', [])
            if not terms:
                continue

            terms.sort(key=lambda x: x.get('end', ''), reverse=True)
            latest_term = terms[0]

            firstname = regex.sub('', member['name']['first'])
            lastname = regex.sub('', member['name']['last'])

            senate_dict = {
                'firstname': firstname,
                'lastname': lastname,
                'id': member['id']['bioguide'],
                'party': latest_term.get('party'),
                'state': latest_term.get('state'),
                'position': latest_term.get('type'),
                'start_term': latest_term.get('start'),
                'end_term': latest_term.get('end')
            }

            if 'official_full' in member['name']:
                senate_dict['fullname'] = regex.sub('', member['name']['official_full'])
            else:
                senate_dict['fullname'] = f"{firstname} {lastname}"

            senate_dicts.append(senate_dict)

        return pd.DataFrame(senate_dicts)

    def create_legislators_table(self, conn):
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS legislators (
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
            self.logger.info("Legislators table created successfully")
        except psycopg2.Error as e:
            self.logger.error(f"Error creating legislators table: {e}")
            conn.rollback()
            raise

    def fetch_existing_legislators(self, engine):
        try:
            query = "SELECT * FROM legislators"
            existing_legislators = pd.read_sql_query(query, engine)
            return existing_legislators
        except pd.io.sql.DatabaseError as e:
            self.logger.error(f"Error fetching existing legislators: {e}")
            return pd.DataFrame()

    def update_database(self, conn, new_data):
        try:
            existing_data = self.fetch_existing_legislators(conn)
            merged_data = pd.concat([existing_data, new_data]).drop_duplicates(subset=['id'], keep='last')

            with conn.cursor() as cursor:
                # Delete all existing rows
                cursor.execute("DELETE FROM legislators")

                # Insert the merged data
                insert_query = """
                    INSERT INTO legislators (fullname, firstname, lastname, id, party, state, position, start_term, end_term)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                data_tuples = [tuple(x) for x in merged_data.to_numpy()]
                cursor.executemany(insert_query, data_tuples)

            self.logger.info("Database updated successfully")
        except (psycopg2.Error, pd.io.sql.DatabaseError) as e:
            self.logger.error(f"Error updating database: {e}")
            conn.rollback()

    def run_daily_update(self):
        try:
            conn = psycopg2.connect(**self.db_params)
            
            # Check if the "legislators" table exists
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'legislators'
                    )
                """)
                table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                self.create_legislators_table(conn)
            
            latest_data = self.process_legislators(self.fetch_legislators_data())
            self.update_database(conn, latest_data)
            
            conn.commit()
            self.logger.info("Daily update completed successfully")
        except psycopg2.Error as e:
            self.logger.error(f"Error during daily update: {e}")
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
    processor.run_daily_update()