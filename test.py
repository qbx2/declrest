import json
import logging

from declrest import endpoint, GET, query, header, f, json_decode, decode, \
    findall, retmap, read_decode, passthru, print_, pprint

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    # using read_decode()
    @endpoint('https://api.ipify.org')
    @read_decode()
    def get_my_ip(params):
        pass

    # using findall, retmap
    @endpoint('http://whatsmyuseragent.org')
    @header('User-Agent', f('{my_user_agent}'))
    @read_decode()
    @findall(r'user-agent.*\s*.*intro-text.*?>([^<]*)')
    @retmap(lambda r: r[0])
    def get_my_user_agent(my_user_agent='DeclREST/1.0', params=None):
        # or
        # params.headers['User-Agent'] = my_user_agent
        pass

    # using passthru, json_decode, print_ and pprint
    @endpoint('https://samples.openweathermap.org')
    @GET('/data/2.5/weather')
    @query('q', 'London,uk')
    @query('appid', 'b6907d289e10d714a6e88b30761fae22')
    @header('User-Agent', 'DeclREST/1.0')
    @passthru(lambda resp: print(resp.headers))
    @read_decode()
    @print_()
    @json_decode()
    @pprint(indent=2)
    def get_weather(params):
        params.headers['X-Powered-By'] = 'declrest'
        print('params:', params)

    # using retmap from params_mutator
    @endpoint('https://samples.openweathermap.org')
    @GET('/data/2.5/weather')
    @query('q', 'London,uk')
    @query('appid', 'b6907d289e10d714a6e88b30761fae22')
    @header('User-Agent', 'DeclREST/1.0')
    def get_weather2(params):
        def retmap(resp):
            return json.loads(resp.read().decode())

        return retmap
        print('params:', params)

    print(get_my_ip())
    print(get_my_user_agent('TEST-UA'))
    print(get_weather())
    print(get_weather2())

    # various formatting methods
    @endpoint(f('https://{cls.__name__}.com/{user_id}/{repo}'))
    class Repo:
        @classmethod
        @GET()  # at least one DeclREST decorator is required
        def get_repo(cls, user_id, repo='declrest', *, params):
            # or
            # params.endpoint = f'{cls.__name__}.com/{user_id}/{repo}'
            pass

    class Github(Repo):
        pass

    Github.get_repo('qbx2')
