import datetime

import psycopg2

import constants

# run port forward:
# k port-forward runai-backend-postgresql-0 32451:5432
# and run this file


db_connection = psycopg2.connect(user="user",
                                 password="password",
                                 host="127.0.0.1",
                                 # port="32451",
                                 port="5432",
                                 database="backend")

def alignProjects():
    projects_names = get_projects()
    print(f"Found {len(projects_names)} projects")

    users = get_all_users()
    print(f"Found {len(users)} users")

    projectsWithoutUsers = list(set(projects_names) - set(users))
    print(f"Found {len(projectsWithoutUsers)} projects without users")

    fixedUsers = 0

    for userName in projectsWithoutUsers:
        createUser(userName)
        setUserResearcherRole(userName)

    for userName in projects_names:
        if addPermissionToProject(userName):
            fixedUsers += 1

    db_connection.commit()
    print(f"Fixed {fixedUsers}")

def createUser(userName: str):
    insert_user_query = f"""
        INSERT INTO backend.auth_user
        (user_id, tenant_id, all_clusters_permitted, client_id, entity_type)
        values ('{userName}', 1, true, '', 'sso-user');
    """
    with db_connection.cursor() as cursor:
        cursor.execute(insert_user_query)


def setUserResearcherRole(userName: str):
    create_role_query = f"""
        INSERT INTO backend.roles
        (user_id, tenant_id, role)
        values ('{userName}', 1, 'researcher');
    """
    with db_connection.cursor() as cursor:
        cursor.execute(create_role_query)


def addPermissionToProject(userName: str) -> bool:
    project_id = None
    with db_connection.cursor() as cursor:
        cursor.execute(f"""
            SELECT project_id FROM backend.projects WHERE project_name='{userName}';
        """)
        project_id = cursor.fetchone()[0]

    with db_connection.cursor() as cursor:
        cursor.execute(f"""
            SELECT COUNT(*) from backend.projects_users_permissions WHERE user_id='{userName}' AND project_id={project_id}
                       """)
        if cursor.fetchone()[0] > 0:
            return False

    project_permission_query = f"""
        INSERT INTO backend.projects_users_permissions
        (project_id, user_id, tenant_id)
        values ({project_id}, '{userName}', 1);
    """
    with db_connection.cursor() as cursor:
        cursor.execute(project_permission_query)

    return True


def get_all_users():
    with db_connection.cursor() as cursor:
        cursor.execute(f"SELECT user_id from backend.auth_user;")
        users = cursor.fetchall()
    return [user[0] for user in users]


def get_projects():
    projects_query = f"""
        SELECT project_name FROM backend.projects;
        """

    with db_connection.cursor() as cursor:
        cursor.execute(projects_query)
        projects = cursor.fetchall()
    return [p[0] for p in projects]


if __name__ == '__main__':
    alignProjects()
    print('Done.')
