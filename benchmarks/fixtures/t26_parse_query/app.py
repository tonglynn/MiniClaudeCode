def parse_query(text):
    return dict(x.split('=') for x in text.split('&'))
