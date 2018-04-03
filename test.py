import logging

from declrest import endpoint, GET, query, body, header, formatted

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    @endpoint('https://api.ipify.org')
    def get_my_ip(spec):
        pass

    @endpoint('http://samples.openweathermap.org/')
    @GET('/data/2.5/weather')
    @query('q', 'London,uk')
    @query('appid', 'b6907d289e10d714a6e88b30761fae22')
    @header(formatted('{method}'), formatted('{method}'))
    @header('test2', formatted('{query[appid]}'))
    @body('test', formatted('{path}'))
    @body('test2', formatted('{headers[User-Agent]}'))
    @header('User-Agent', 'DeclREST/1.0')
    def get_weather(spec):
        spec.headers['X-Powered-By'] = 'declrest'
        print('params:', spec)

    print(get_my_ip().read())
    print(get_weather().read())
