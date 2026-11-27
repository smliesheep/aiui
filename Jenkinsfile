pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 40, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        PYTHONUTF8 = '1'
        AIUI_HEADLESS = 'true'
        // API Key 从 Jenkins 凭据注入，绝不写进仓库
        AIUI_DEEPSEEK_API_KEY = credentials('deepseek-api-key')
    }

    stages {
        stage('Setup') {
            steps {
                bat '''
                    if not exist .venv python -m venv .venv
                    .venv\\Scripts\\python -m pip install --upgrade pip
                    .venv\\Scripts\\python -m pip install -e ".[dev]"
                '''
            }
        }

        stage('Framework Unit Tests') {
            steps {
                bat '.venv\\Scripts\\python -m pytest -q -k "not e2e and not plan_executes" --junitxml=artifacts\\junit-unit.xml'
            }
        }

        stage('E2E (demo page)') {
            steps {
                bat '.venv\\Scripts\\python -m pytest -q tests\\test_e2e_demo.py --alluredir=artifacts\\allure-results'
            }
        }

        stage('Plan Regression') {
            steps {
                bat '.venv\\Scripts\\python -m pytest -q tests\\test_plans.py --alluredir=artifacts\\allure-results'
            }
        }
    }

    post {
        always {
            bat '''
                if exist allure-report rmdir /s /q allure-report
                allure generate artifacts\\allure-results -o allure-report --clean
            '''
            publishHTML(target: [
                allowMissing: true,
                alwaysLinkToLastBuild: true,
                keepAll: true,
                reportDir: 'allure-report',
                reportFiles: 'index.html',
                reportName: 'AIUI Allure Report'
            ])
            junit allowEmptyResults: true, testResults: 'artifacts\\junit-*.xml'
            archiveArtifacts artifacts: 'artifacts/**/99-summary.json', allowEmptyArchive: true
        }
    }
}
