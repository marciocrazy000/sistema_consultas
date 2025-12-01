import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_mysqldb import MySQL

# --- Configurações da Aplicação Flask ---
app = Flask(__name__)
# Chave secreta para gerenciar sessões
app.secret_key = os.urandom(24)

# --- Configurações do MySQL (Configure suas credenciais) ---
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'saep1'
app.config['MYSQL_DB'] = 'sistema_consultas'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)


# --------------------------------------------------------------------------------------------------
# --- Funções Auxiliares de Autenticação e Permissão ---
# --------------------------------------------------------------------------------------------------

def autenticado():
    """Verifica se o usuário está logado na sessão."""
    return 'usuario_logado' in session


def obter_usuario_logado():
    """Retorna os dados do usuário logado."""
    return {
        'nome': session.get('nome_usuario', 'Usuário'),
        'cargo': session.get('cargo_usuario', 'Sem Cargo'),
        'id': session.get('id_usuario')
    }


def permite_cargo(cargos_permitidos):
    """
    Verifica se o usuário logado possui um dos cargos permitidos.
    Redireciona para o dashboard ou login se não tiver permissão.
    """
    if not autenticado():
        flash('Sua sessão expirou.', 'danger')
        return redirect(url_for('login'))

    cargo_usuario = session.get('cargo_usuario')

    # O cargo ADMINISTRADOR sempre tem acesso a tudo
    if cargo_usuario == 'ADMINISTRADOR':
        return None

    if cargo_usuario not in cargos_permitidos:
        flash('Acesso negado: Você não tem permissão para acessar esta página.', 'danger')
        return redirect(url_for('dashboard'))

    return None  # Retorna None se o acesso for permitido


# Adiciona variáveis globais e filtros ao contexto dos templates
@app.context_processor
def inject_global_vars():
    def format_time(value):
        """Formata objetos time ou datetime para HH:MM."""
        if hasattr(value, 'strftime'):
            return value.strftime('%H:%M')
        return str(value)

    def format_timedelta(value):
        """Formata objetos timedelta (duração) para HH:MM."""
        if isinstance(value, timedelta):
            total_seconds = int(value.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours:02d}:{minutes:02d}"
        return format_time(value)

    # Função para determinar se um item de menu deve ser exibido
    def menu_visivel(menu_cargos):
        cargo_usuario = session.get('cargo_usuario')
        return cargo_usuario == 'ADMINISTRADOR' or cargo_usuario in menu_cargos

    return dict(
        autenticado=autenticado,
        datetime=datetime,
        now=datetime.now,
        format_time=format_time,
        format_timedelta=format_timedelta,
        menu_visivel=menu_visivel,
        cargo_usuario=session.get('cargo_usuario')  # Permite acesso direto ao cargo no HTML
    )


# --------------------------------------------------------------------------------------------------
# --- Rotas de Autenticação ---
# --------------------------------------------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def login():
    if autenticado():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']

        cur = mysql.connection.cursor()
        # SELECIONA O CAMPO CARGO AQUI
        cur.execute("SELECT id, nome, senha, cargo FROM usuarios WHERE email = %s", [email])
        usuario = cur.fetchone()
        cur.close()

        if usuario:
            # COMPARAÇÃO EM TEXTO SIMPLES (NÃO USE HASH)
            if senha == usuario['senha']:
                session['usuario_logado'] = True
                session['id_usuario'] = usuario['id']
                session['nome_usuario'] = usuario['nome']
                session['cargo_usuario'] = usuario['cargo']  # SALVA O CARGO NA SESSÃO
                flash('Login realizado com sucesso!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Credenciais Inválidas. Tente novamente.', 'danger')
        else:
            flash('Credenciais Inválidas. Tente novamente.', 'danger')

    return render_template('login.html', titulo="Login")


@app.route('/logout')
def logout():
    session.clear()
    flash('Sessão encerrada com sucesso.', 'info')
    return redirect(url_for('login'))


# --------------------------------------------------------------------------------------------------
# --- Rotas Principais (Com Permissões) ---
# --------------------------------------------------------------------------------------------------

@app.route('/dashboard')
def dashboard():
    # Primeira checagem: Se não estiver autenticado, vai para o login
    if not autenticado():
        flash('Sua sessão expirou.', 'danger')
        return redirect(url_for('login'))

    usuario = obter_usuario_logado()

    # TRATAMENTO PARA PACIENTE: Redireciona-o para a rota principal dele.
    if usuario['cargo'] == 'PACIENTE':
        return redirect(url_for('agendar_consulta'))

    # Checagem de permissão final para o dashboard
    if usuario['cargo'] not in ['MEDICO', 'ADMINISTRADOR']:
        flash('Acesso negado: Cargo não autorizado para dashboard.', 'danger')
        return redirect(url_for('login'))  # Se não for ADMIN/MEDICO/PACIENTE, envia para o login

    cur = mysql.connection.cursor()

    # 1. Obter total de consultas AGENDADAS
    cur.execute("SELECT COUNT(*) AS total FROM consultas WHERE status = 'AGENDADA' AND data >= CURDATE()")
    agendadas_futuras = cur.fetchone()['total']

    # 2. Obter consultas de hoje (ID REMOVIDO DA SELEÇÃO para exibição no template)
    cur.execute("""
        SELECT 
            p.nome AS paciente_nome, c.hora, c.tipo_consulta
        FROM consultas c
        JOIN pacientes p ON c.paciente_id = p.id
        WHERE c.data = CURDATE() AND c.status = 'AGENDADA'
        ORDER BY c.hora
    """)
    consultas_hoje = cur.fetchall()

    # 3. Obter total de pacientes cadastrados
    cur.execute("SELECT COUNT(*) AS total FROM pacientes")
    total_pacientes = cur.fetchone()['total']

    cur.close()

    return render_template('dashboard.html',
                           usuario=usuario,
                           agendadas_futuras=agendadas_futuras,
                           consultas_hoje=consultas_hoje,
                           total_pacientes=total_pacientes
                           )


@app.route('/paciente/cadastrar', methods=['GET', 'POST'])
def cadastro_paciente():
    # PERMISSÃO: APENAS ADMINISTRADOR (Pode ser removida se o cadastro for público)
    permissao = permite_cargo(['ADMINISTRADOR'])
    if permissao: return permissao

    usuario = obter_usuario_logado()

    if request.method == 'POST':
        nome = request.form['nome']
        cpf = request.form['cpf']
        telefone = request.form['telefone']
        data_nascimento = request.form['data_nascimento']
        historico = request.form['historico_basico']

        # NOVOS CAMPOS PARA CRIAÇÃO DO USUÁRIO PACIENTE
        email = request.form['email']
        senha = request.form['senha']

        try:
            cur = mysql.connection.cursor()

            # --- 1. TENTA INSERIR O USUÁRIO (LOGIN) ---
            cur.execute("SELECT id FROM usuarios WHERE email = %s", [email])
            if cur.fetchone():
                flash('Erro ao cadastrar: Email já registrado como usuário.', 'danger')
                cur.close()
                return redirect(url_for('cadastro_paciente'))

            # Insere na tabela 'usuarios' com cargo 'PACIENTE'
            cur.execute("""
                INSERT INTO usuarios (nome, email, senha, cargo) 
                VALUES (%s, %s, %s, 'PACIENTE')
            """, (nome, email, senha))

            # Não precisamos mais do usuario_id, pois não vamos usá-lo na tabela 'pacientes'

            # --- 2. TENTA INSERIR O CADASTRO DO PACIENTE (CORRIGIDO) ---
            # Removemos 'usuario_id_fk' da query
            cur.execute("""
                INSERT INTO pacientes (nome, cpf, telefone, data_nascimento, historico_basico) 
                VALUES (%s, %s, %s, %s, %s)
            """, (nome, cpf, telefone, data_nascimento, historico))

            mysql.connection.commit()
            cur.close()
            flash(
                f'Paciente {nome} cadastrado e conta de acesso criada com sucesso! Ele pode acessar com o email {email}.',
                'success')
            return redirect(url_for('login'))  # Redireciona para o login após o cadastro

        except Exception as e:
            mysql.connection.rollback()
            if 'Duplicate entry' in str(e) and 'cpf' in str(e).lower():
                flash('Erro ao cadastrar: CPF já registrado.', 'danger')
            else:
                flash(f'Erro ao cadastrar paciente: {e}', 'danger')

    return render_template('cadastro_paciente.html', usuario=usuario, titulo="Cadastro de Paciente")


@app.route('/consulta/agendar', methods=['GET', 'POST'])
def agendar_consulta():
    # PERMISSÃO: ADMINISTRADOR, MÉDICO, PACIENTE
    permissao = permite_cargo(['MEDICO', 'PACIENTE'])
    if permissao: return permissao

    usuario = obter_usuario_logado()

    # Se o usuário for PACIENTE, ele só pode agendar para si mesmo.
    pacientes_listagem = []
    paciente_pre_selecionado = None

    if usuario['cargo'] == 'PACIENTE':
        cur = mysql.connection.cursor()
        # Buscando o paciente cujo NOME corresponde ao nome de login do usuário (simplificação)
        # É mais seguro buscar pelo ID do usuário (session['id_usuario']) se a FK 'usuario_id_fk' estiver na tabela 'pacientes'
        cur.execute("SELECT id, nome, cpf FROM pacientes WHERE nome = %s LIMIT 1", [usuario['nome']])
        paciente_pre_selecionado = cur.fetchone()
        cur.close()

        # Se encontrou, a lista só tem ele
        if paciente_pre_selecionado:
            pacientes_listagem = [paciente_pre_selecionado]
        else:
            # CORREÇÃO: Paciente logado, mas sem perfil de paciente na tabela 'pacientes'.
            flash(
                'Erro crítico: Seu perfil de paciente não foi encontrado no cadastro de pacientes. Você foi deslogado. Contate a administração.',
                'danger')

            # Limpa a sessão e redireciona para login
            session.clear()
            return redirect(url_for('login'))
    else:
        # ADMIN/MEDICO podem ver todos os pacientes
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, nome, cpf FROM pacientes ORDER BY nome")
        pacientes_listagem = cur.fetchall()
        cur.close()

    if request.method == 'POST':
        paciente_id = request.form['paciente_id']
        data = request.form['data']
        hora = request.form['hora']
        tipo_consulta = request.form['tipo_consulta']
        agendador_id = usuario['id']

        # Se for PACIENTE, verifica se ele está tentando agendar para outra pessoa
        if usuario['cargo'] == 'PACIENTE' and pacientes_listagem and str(paciente_id) != str(
                pacientes_listagem[0]['id']):
            flash('Você só pode agendar consultas para si mesmo.', 'danger')
            return redirect(url_for('agendar_consulta'))

        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT * FROM consultas WHERE data = %s AND hora = %s AND status = 'AGENDADA'", (data, hora))
            if cur.fetchone():
                cur.close()
                flash('Erro: Já existe uma consulta AGENDADA neste horário.', 'danger')
                return redirect(url_for('agendar_consulta'))

            cur.execute("""
                INSERT INTO consultas (paciente_id, data, hora, tipo_consulta, agendado_por_id) 
                VALUES (%s, %s, %s, %s, %s)
            """, (paciente_id, data, hora, tipo_consulta, agendador_id))
            mysql.connection.commit()
            cur.close()
            flash('Consulta agendada com sucesso!', 'success')
            return redirect(url_for('agendar_consulta'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Erro ao agendar consulta: {e}', 'danger')

    return render_template('agendar_consulta.html',
                           usuario=usuario,
                           pacientes=pacientes_listagem,
                           titulo="Agendar Consulta"
                           )


@app.route('/agendamentos/futuros')
def listar_agendamentos():
    # PERMISSÃO: ADMINISTRADOR, MÉDICO
    permissao = permite_cargo(['MEDICO'])
    if permissao: return permissao

    usuario = obter_usuario_logado()

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            c.id, p.nome AS paciente_nome, p.cpf, c.data, c.hora, c.tipo_consulta, c.status
        FROM consultas c
        JOIN pacientes p ON c.paciente_id = p.id
        WHERE c.status = 'AGENDADA' AND c.data >= CURDATE()
        ORDER BY c.data ASC, c.hora ASC
    """)
    agendamentos = cur.fetchall()
    cur.close()

    return render_template('listar_agendamentos.html', usuario=usuario, agendamentos=agendamentos,
                           titulo="Gerenciar Agendamentos")


@app.route('/agendamento/<int:consulta_id>/<action>', methods=['POST'])
def gerenciar_agendamento(consulta_id, action):
    # PERMISSÃO: ADMINISTRADOR, MÉDICO
    permissao = permite_cargo(['MEDICO'])
    if permissao: return permissao

    try:
        cur = mysql.connection.cursor()

        if action == 'cancelar':
            cur.execute("UPDATE consultas SET status = 'CANCELADA' WHERE id = %s AND status = 'AGENDADA'",
                        [consulta_id])
            msg = 'Agendamento cancelado com sucesso.'

        elif action == 'realizar':
            cur.execute("UPDATE consultas SET status = 'REALIZADA' WHERE id = %s AND status = 'AGENDADA'",
                        [consulta_id])
            msg = 'Consulta marcada como REALIZADA. Prossiga para o Registro de Atendimento.'
        else:
            flash('Ação inválida.', 'danger')
            return redirect(url_for('listar_agendamentos'))

        mysql.connection.commit()
        cur.close()
        flash(msg, 'success')
        return redirect(url_for('listar_agendamentos'))

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Erro ao processar a ação: {e}', 'danger')
        return redirect(url_for('listar_agendamentos'))


@app.route('/atendimento/registrar', methods=['GET', 'POST'])
def registrar_atendimento():
    # PERMISSÃO: ADMINISTRADOR, MÉDICO
    permissao = permite_cargo(['MEDICO'])
    if permissao: return permissao

    usuario = obter_usuario_logado()

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            c.id, p.nome AS paciente_nome, c.data, c.hora, c.tipo_consulta
        FROM consultas c
        JOIN pacientes p ON c.paciente_id = p.id
        LEFT JOIN atendimentos a ON c.id = a.consulta_id
        WHERE c.status = 'REALIZADA' AND a.consulta_id IS NULL
        ORDER BY c.data DESC, c.hora DESC
    """)
    consultas_pendentes = cur.fetchall()
    cur.close()

    if request.method == 'POST':
        consulta_id = request.form['consulta_id']
        descricao = request.form['descricao']

        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO atendimentos (consulta_id, descricao) 
                VALUES (%s, %s)
            """, (consulta_id, descricao))
            mysql.connection.commit()
            cur.close()
            flash('Atendimento registrado com sucesso!', 'success')
            return redirect(url_for('registrar_atendimento'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Erro ao registrar atendimento: {e}', 'danger')

    return render_template('registrar_atendimento.html',
                           usuario=usuario,
                           consultas_pendentes=consultas_pendentes,
                           titulo="Registrar Atendimento"
                           )


@app.route('/historico/paciente', methods=['GET', 'POST'])
def historico_paciente():
    # PERMISSÃO: ADMINISTRADOR, MÉDICO
    permissao = permite_cargo(['MEDICO'])
    if permissao: return permissao

    usuario = obter_usuario_logado()
    historico = []
    paciente_encontrado = None

    cur = mysql.connection.cursor()
    cur.execute("SELECT id, nome, cpf FROM pacientes ORDER BY nome")
    pacientes_list = cur.fetchall()
    cur.close()

    if request.method == 'POST':
        paciente_id = request.form['paciente_id']

        cur = mysql.connection.cursor()
        cur.execute("SELECT id, nome, cpf, telefone, historico_basico FROM pacientes WHERE id = %s", [paciente_id])
        paciente_encontrado = cur.fetchone()

        if paciente_encontrado:
            cur.execute("""
                SELECT 
                    c.data, c.hora, c.tipo_consulta, c.status, a.descricao AS evolucao, u.nome AS atendente
                FROM consultas c
                LEFT JOIN atendimentos a ON c.id = a.consulta_id
                LEFT JOIN usuarios u ON c.agendado_por_id = u.id
                WHERE c.paciente_id = %s
                ORDER BY c.data DESC, c.hora DESC
            """, [paciente_id])
            historico = cur.fetchall()

        cur.close()

    return render_template('historico_paciente.html',
                           usuario=usuario,
                           pacientes_list=pacientes_list,
                           paciente_encontrado=paciente_encontrado,
                           historico=historico,
                           titulo="Histórico por Paciente"
                           )


@app.route('/relatorio/periodo', methods=['GET', 'POST'])
def relatorio_periodo():
    # PERMISSÃO: ADMINISTRADOR, MÉDICO
    permissao = permite_cargo(['MEDICO'])
    if permissao: return permissao

    usuario = obter_usuario_logado()
    relatorio = None
    data_inicio = ""
    data_fim = ""

    if request.method == 'POST':
        data_inicio = request.form['data_inicio']
        data_fim = request.form['data_fim']

        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT 
                    c.data, c.hora, p.nome AS paciente_nome, c.tipo_consulta, c.status, 
                    u.nome AS agendado_por, a.descricao AS evolucao
                FROM consultas c
                JOIN pacientes p ON c.paciente_id = p.id
                LEFT JOIN usuarios u ON c.agendado_por_id = u.id
                LEFT JOIN atendimentos a ON c.id = a.consulta_id
                WHERE c.data BETWEEN %s AND %s
                ORDER BY c.data ASC, c.hora ASC
            """, (data_inicio, data_fim))
            relatorio = cur.fetchall()
            cur.close()

        except Exception as e:
            flash(f'Erro ao gerar relatório: {e}', 'danger')
            relatorio = []

    return render_template('relatorio_periodo.html',
                           usuario=usuario,
                           relatorio=relatorio,
                           data_inicio=data_inicio,
                           data_fim=data_fim,
                           titulo="Relatório por Período"
                           )


# --- Rota de Verificação de Horário (AJAX) ---
@app.route('/api/verificar_horario', methods=['POST'])
def verificar_horario():
    # PERMISSÃO: ADMINISTRADOR, MÉDICO, PACIENTE
    if not autenticado():
        return jsonify({'disponivel': False, 'mensagem': 'Sessão expirada'}), 401

    cargo = session.get('cargo_usuario')
    if cargo not in ['ADMINISTRADOR', 'MEDICO', 'PACIENTE']:
        return jsonify({'disponivel': False, 'mensagem': 'Não autorizado'}), 403

    data = request.json.get('data')
    hora = request.json.get('hora')

    if not data or not hora:
        return jsonify({'disponivel': False, 'mensagem': 'Dados incompletos'}), 400

    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT COUNT(*) AS total FROM consultas WHERE data = %s AND hora = %s AND status = 'AGENDADA'",
                    (data, hora))
        resultado = cur.fetchone()
        cur.close()

        total = resultado['total']
        disponivel = total == 0

        if disponivel:
            mensagem = "Horário disponível para agendamento."
        else:
            mensagem = "Horário já ocupado por outra consulta AGENDADA."

        return jsonify({'disponivel': disponivel, 'mensagem': mensagem})

    except Exception as e:
        return jsonify({'disponivel': False, 'mensagem': f'Erro no banco de dados: {e}'}), 500


# --- Execução da Aplicação ---
if __name__ == '__main__':

    app.run(debug=True, host='0.0.0.0', port=5000)
