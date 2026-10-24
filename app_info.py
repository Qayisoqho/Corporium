"""Application identity shared by the desktop shell and About page."""
VERSION = '0.9.01024'
NAME = 'Corporium'
DEVELOPER = 'Erči Ša.'
PROJECT_URL = 'https://github.com/Qayisoqho/Corporium'


def about():
    return {'name': NAME, 'version': VERSION, 'developer': DEVELOPER,
            'description': '面向田野语言学调查的本地语料工作区。',
            'project_url': PROJECT_URL, 'issues_url': PROJECT_URL + '/issues'}
