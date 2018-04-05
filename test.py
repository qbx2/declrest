import logging

from declrest import endpoint, GET, query, form, header, f, body, \
    json_decode, decode, findall, rethook

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    @endpoint('https://api.ipify.org')
    @decode()
    def get_my_ip(params):
        pass

    @endpoint('http://whatsmyuseragent.org')
    @header('User-Agent', f('{my_user_agent}'))
    @findall(r'user-agent.*\s*.*intro-text.*?>([^<]*)')
    @rethook(lambda r: r[0])
    def get_my_user_agent(my_user_agent='DeclREST/1.0', params=None):
        # or
        params.headers['User-Agent'] = my_user_agent

    @endpoint('http://samples.openweathermap.org')
    @GET('/data/2.5/weather')
    @query('q', 'London,uk')
    @query('appid', 'b6907d289e10d714a6e88b30761fae22')
    @header(f('{method}'), f('{method}'))
    @header('test2', f('{query[appid]}'))
    @header('test3', f('{form[test2]}'))
    @form('test', f('{path}'))
    @form('test2', f('{headers[User-Agent]}'))
    @header('User-Agent', 'DeclREST/1.0')
    @body('test')
    @json_decode()
    def get_weather(params):
        params.headers['X-Powered-By'] = 'declrest'
        print('params:', params)

    print(get_my_ip())
    print(get_my_user_agent('TEST-UA'))
    print(get_weather())

    class Repo:
        @classmethod
        @endpoint(f('https://{cls.__name__}.com/{user_id}/{repo}'))
        @decode()
        def get_repo(cls, user_id, repo='declrest', *, params):
            # or
            params.endpoint = f'{cls.__name__}.com/{user_id}/{repo}'

    class Github(Repo):
        pass

    Github.get_repo('qbx2')
