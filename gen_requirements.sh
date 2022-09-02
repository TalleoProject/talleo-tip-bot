#!/bin/bash
pipenv requirements | grep -v '^\-i ' | cut -d ';' -f 1 - | cut -d ' ' -f 1 - > requirements.txt
pipenv requirements --dev | grep -v '^\-i ' | cut -d ';' -f 1 - | cut -d ' ' -f 1 - > requirements-dev.txt
