"""Betfair Python API.
Copyright 2017 Mark Mitterdorfer

A Betfair API for Python 3
"""

import requests
import base64
import time
import json
import datetime
import logging
import threading

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())
# Only log warnings from requests, otherwise info overload!
logging.getLogger("requests").setLevel(logging.WARNING)

class BetfairException(Exception):
    pass


class Betfair:

    betting_url = "https://api.betfair.com/exchange/betting/json-rpc/v1"
    accounts_url = "https://api.betfair.com/exchange/account/json-rpc/v1"
    
    def __init__(self, app_key: str, alive_refresh_sec=7200):
        """
        Init, alive_refresh default to two hours for the keep alive thread
        """
        self.app_key = app_key
        self.login_status = ""
        self.session_token = ""
        self.__alive_thread = None
        self.alive_refresh_sec = alive_refresh_sec

    def __call_aping(self, jsonrpc_req: str, url: str):
        headers = {'X-Application': self.app_key, 'X-Authentication': self.session_token, 'content-type': 'application/json'}
        # Replace all ' single quotes in JSON requests to " double quotes to make it compliant with JSON standard
        # jsonrpc_req = jsonrpc_req.replace("'", "\"")
        return requests.post(url, data=jsonrpc_req, headers=headers).json()
    
    def login(self, username: str, password: str):
        """
        Login to Betfair, username and password to be base64 encoded (to prevent someone prying eyes!)
        Be sure to have your .crt and .key file in the same location as this file
        """

        payload = 'username=%s&password=%s' % (base64.b64decode(username).decode("ascii"), base64.b64decode(password).decode("ascii"))
        headers = {'X-Application': 'SomeKey', 'Content-Type': 'application/x-www-form-urlencoded'}
 
        resp = requests.post('https://identitysso.betfair.com/api/certlogin', data=payload, cert=('client-2048.crt', 'client-2048.key'), headers=headers)
 
        if resp.status_code == 200:
            resp_json = resp.json()
            if resp_json['loginStatus'] == 'INVALID_USERNAME_OR_PASSWORD':
                log.error("Login failed - invalid username or password")
                raise BetfairException("login:loginStatus", "INVALID_USERNAME_OR_PASSWORD")
            self.login_status = resp_json['loginStatus']
            self.session_token = resp_json['sessionToken']
        else:
            log.critical("Login failed - unknown error")
            raise BetfairException("login", "Unknown error")

        log.info("Login status: {}".format(self.login_status))
        log.info("Session token: {}".format(self.session_token))

        log.info("Starting keep alive thread")
        self.__alive_thread = threading.Thread(target=self.__keep_alive_thread, daemon=True)
        self.__alive_thread.start()

    def __keep_alive_thread(self):
        log.info("Keep alive thread started and set to {0:d} seconds".format(self.alive_refresh_sec))
        while True:
            self.keep_alive()
            log.info("Keeping alive ...")
            time.sleep(self.alive_refresh_sec)

    def keep_alive(self):
        """
        Keep the session alive, call this in a thread every hour to be safe
        """

        headers = {'Accept': 'application/json', 'X-Application': self.app_key, 'X-Authentication': self.session_token}
        resp = requests.post('https://identitysso.betfair.com/api/keepAlive', data='', headers=headers)

        if resp.status_code == 200:
            resp_json = resp.json()
            if resp_json['status'] == 'FAIL':
                raise BetfairException("keepAlive:status", "FAIL")
            elif resp_json['error'] != '':
                raise BetfairException("keepAlive:error", resp_json['error'])
        else:
            raise BetfairException("keepAlive", "Unknown error")

    def get_gbp_funds(self) -> float:
        """
        Obtain funds in GBP wallet
        """
        
        account_req = '{"jsonrpc": "2.0", "method": "AccountAPING/v1.0/getAccountFunds", "params": {"wallet":"UK"}, "id": 1}'
        account_response = self.__call_aping(jsonrpc_req=account_req, url=Betfair.accounts_url)
        return float((account_response['result']['availableToBetBalance']))
        
    def get_football_competitions(self) -> list:
        """
        Obtain a list of football competitions
        """
        
        football_req = '{"jsonrpc": "2.0", "method": "SportsAPING/v1.0/listCompetitions", "params": {"filter":{"eventTypeIds":["1"]}}, "id": 1}'
        footballResponse = self.__call_aping(jsonrpc_req=football_req, url=Betfair.betting_url)
        competitions = [i['competition'] for i in footballResponse['result']]
        return competitions

    def get_football_games(self, football_competition_id: str) -> list:
        """
        Get a list of football games from a competition id
        """
        football_ids_req = '{"jsonrpc": "2.0", "method": "SportsAPING/v1.0/listEvents", "params": {"filter": {"competitionIds":["%s"]}}, "id": 1}' % (football_competition_id)
        football_ids_response = self.__call_aping(jsonrpc_req=football_ids_req, url=Betfair.betting_url)
        # Make sure we only obtain HvA that is team Home vs. team Away
        games = [i['event'] for i in football_ids_response['result'] if ' v ' in i['event']['name']]
        return games

    def get_events_data(self, *market_ids: str):
        """
        Get event information based off the market ids
        """
        event_req = '{"jsonrpc": "2.0", "method": "SportsAPING/v1.0/listEvents", "params": {"filter": {"marketIds": [%s]}}, "id": 1}' % (
            ','.join(market_ids))

        event_response = self.__call_aping(jsonrpc_req=event_req, url=Betfair.betting_url)
        return event_response

    def get_market_catalogue(self, event_id: str, market_type_code: str) -> str:
        """
        Obtain the marketCatalogue from an event id and market code type
        """
        market_req = '{"jsonrpc": "2.0", "method": "SportsAPING/v1.0/listMarketCatalogue", "params": {"filter": {"eventIds": ["%s"], "marketTypeCodes": ["%s"]}, "maxResults": "1"}, "id": 1}' % (
            event_id, market_type_code)
        market_response = self.__call_aping(jsonrpc_req=market_req, url=Betfair.betting_url)
        return market_response['result'][0]

    def get_football_game_description(self, market_id: str) -> str:
        """
        Obtain football game description
        """
        game_desc_req = '{"jsonrpc": "2.0", "method": "SportsAPING/v1.0/listMarketCatalogue", "params": {"filter": {"marketIds": [%s]}, "maxResults": "1", "marketProjection": ["RUNNER_DESCRIPTION"]}, "id": 1}' % (market_id)
        game_desc_response = self.__call_aping(jsonrpc_req=game_desc_req, url=Betfair.betting_url)
        return game_desc_response

    def get_market_data(self, *market_ids: str) -> dict:
        """
        Obtain current market data
        NOTE, market_ids must be surrounded by quotes i.e. "market_id1","market_id2" otherwise the call may return empty json string
        """
        # !!Delay app key only returns 3 prices, i.e. it is not possible to override the market book depth!!
        # market_data_req = '{"jsonrpc": "2.0", "method": "SportsAPING/v1.0/listMarketBook", "params": {"marketIds":[%s],"priceProjection":{"priceData":["EX_BEST_OFFERS"],"virtualise":"true"},"orderProjection":"EXECUTABLE"}, "id": 1}' % (
        #    ','.join(market_ids))
        market_data_req = '{"jsonrpc": "2.0", "method": "SportsAPING/v1.0/listMarketBook", "params": {"marketIds":[%s],"priceProjection":{"priceData":["EX_BEST_OFFERS"],"virtualise":"true"},"orderProjection":"EXECUTABLE","matchProjection":"ROLLED_UP_BY_AVG_PRICE"}, "id": 1}' % (
            ','.join(market_ids))

        market_data_response = self.__call_aping(jsonrpc_req=market_data_req, url=Betfair.betting_url)
        return market_data_response

def main():
    try:
        # Use delayed appkey
        session = Betfair(app_key="[YOUR APP KEY]")
        session.login(username="[YOUR USERNAME IN BASE64]", password="[YOUR PASSWORD IN BASE64]")
        print(session.login_status, session.session_token)
        
        # Demonstrate two sessions running concurrently
        session2 = Betfair(app_key="[YOUR APP KEY]")
        session2.login(username="[YOUR USERNAME IN BASE64]", password="[YOUR PASSWORD IN BASE64]")
        print(session2.login_status, session2.session_token)
        
        print(session.get_gbp_funds())
        # Get id of 'English Premier League'
        id_english = None
        for i in session.get_football_competitions():
            if i['name'] == 'English Premier League':
                id_english = i['id']
                break
        
        if id_english != None:
            # Display all games in the Premier League
            for i in session.get_football_games(id_english):
                print(i)

        # Get the game name of first entry
        game_name = session.get_football_games(id_english)[0]['name']
        print("Game name:", game_name)
        # Get the unique event id for that game
        game_eventid = session.get_football_games(id_english)[0]['id']
        # Get the market id for match odds (i.e. Home, Away, Draw)
        game_marketid = session.get_market_catalogue(game_eventid, 'MATCH_ODDS')['marketId']
        # Get game info, name of teams etc.
        game_desc = session.get_football_game_description(game_marketid)
        game_marketdata = session.get_market_data(game_marketid)
        game_runners = game_desc['result'][0]['runners']
        # Sort the game runners according to sortPriority
        game_runners = sorted(game_runners, key=lambda k: k['sortPriority'])
        home_team = game_runners[0]
        print(home_team)

        game_eventid2 = session.get_football_games(id_english)[1]['id']
        # Get the market id for match odds (i.e. Home, Away, Draw)
        game_marketid2 = session2.get_market_catalogue(game_eventid2, 'MATCH_ODDS')['marketId']

    except KeyboardInterrupt:
        print("Caught Ctrl-C existing")


if __name__ == "__main__":
     main()
