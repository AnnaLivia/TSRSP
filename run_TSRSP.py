import sys
import os
import csv
import time
from collections import defaultdict

TIME_LIMIT = 300
EPS = 1e-9

##############################################################################
# READERS AND GRAPH STRUCTURES
##############################################################################

def read_instance(folder):
    basename = os.path.basename(folder.rstrip(os.sep))

    datafile = os.path.join(folder, basename + ".data")
    pfile = os.path.join(folder, basename + ".p")
    qfile = os.path.join(folder, basename + ".q")
    rfile = os.path.join(folder, basename + ".r")

    edges = []
    n = None
    m = None

    with open(datafile) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                n = int(parts[2])
                m = int(parts[3])
            elif line.startswith("e"):
                _, u, v = line.split()
                edges.append((int(u), int(v)))

    if n is None:
        raise ValueError(f"Missing p edge line in {datafile}")

    min_vertex = min(min(u, v) for u, v in edges) if edges else 0
    max_vertex = max(max(u, v) for u, v in edges) if edges else n - 1
    if min_vertex == 1 and max_vertex == n:
        edges = [(u - 1, v - 1) for u, v in edges]
    elif min_vertex < 0 or max_vertex >= n:
        raise ValueError("Vertex indices are inconsistent with n. Expected either 0..n-1 or 1..n.")

    layers = []
    with open(pfile) as f:
        for line in f:
            line = line.strip()
            if line:
                layers.append(int(line))

    route_cost = []
    with open(qfile) as f:
        for line in f:
            line = line.strip()
            if line:
                route_cost.append(float(line))

    edge_cost = []
    with open(rfile) as f:
        for line in f:
            line = line.strip()
            if line:
                edge_cost.append(float(line))

    if len(layers) != n:
        raise ValueError(f"Expected {n} layer entries, found {len(layers)}")
    if len(route_cost) != n:
        raise ValueError(f"Expected {n} route costs, found {len(route_cost)}")
    if len(edges) != len(edge_cost):
        raise ValueError(f"Expected one edge cost per edge, found {len(edge_cost)} for {len(edges)} edges")
    if m is not None and m != len(edges):
        print(f"Warning: p edge declares {m} edges but file contains {len(edges)} edges")

    return n, edges, layers, route_cost, edge_cost


def build_graph(edges, layers, edge_cost):
    E = {}
    N = defaultdict(set)

    for (u, v), c in zip(edges, edge_cost):
        E[(u, v)] = c
        E[(v, u)] = c
        N[u].add(v)
        N[v].add(u)

    layer_vertices = defaultdict(list)
    for v, l in enumerate(layers):
        layer_vertices[l].append(v)

    K = sorted(layer_vertices.keys())

    anti_edges = []
    for a in range(len(K)):
        for b in range(a + 1, len(K)):
            for u in layer_vertices[K[a]]:
                for v in layer_vertices[K[b]]:
                    if v not in N[u]:
                        anti_edges.append((u, v))

    return K, layer_vertices, E, N, anti_edges


def compute_layer_bounds(V, layers, N, E, layer_vertices):
    Dminus = {}
    Dplus = {}
    fixed_zero = []

    for r in V:
        layer_r = layers[r]
        dmin = 0.0
        dmax = 0.0
        feasible = True

        for l in layer_vertices:
            if l == layer_r:
                continue
            costs = [E[(r, s)] for s in N[r] if layers[s] == l]
            if not costs:
                feasible = False
                break
            dmin += min(costs)
            dmax += max(costs)

        if feasible:
            Dminus[r] = dmin
            Dplus[r] = dmax
        else:
            Dminus[r] = 0.0
            Dplus[r] = 0.0
            fixed_zero.append(r)

    return Dminus, Dplus, fixed_zero


def is_layer_wise_complete(anti_edges):
    return len(anti_edges) == 0

##############################################################################
# GUROBI BUILDERS
##############################################################################

def import_gurobi():
    try:
        import gurobipy as gp
        from gurobipy import GRB
        return gp, GRB
    except ImportError as exc:
        raise ImportError("Gurobi was requested, but gurobipy is not installed.") from exc


def add_clique_constraints_gurobi(gp, model, x, clique_type, V, anti_edges, layers):
    if clique_type is None:
        return
    if clique_type not in {"a", "b"}:
        raise ValueError("clique_type must be 'a', 'b', 'c', or None")

    if clique_type == "a":
        for u, v in anti_edges:
            model.addConstr(x[u] + x[v] <= 1, name=f"nonedge_{u}_{v}")
        return

    antiN = {r: [] for r in V}
    for u, v in anti_edges:
        antiN[u].append(v)
        antiN[v].append(u)

    n_layers = len(set(layers))
    for r in V:
        if not antiN[r]:
            continue
        rhs = min(len(antiN[r]), n_layers - 1)
        model.addConstr(gp.quicksum(x[s] for s in antiN[r]) <= rhs * (1 - x[r]), name=f"antineigh_{r}")


def build_gurobi_model(model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers, lp=False):
    gp, GRB = import_gurobi()
    env = gp.Env(params={"OutputFlag": 0})

    if model_name == "S":
        m = gp.Model("S", env=env)
        vtype = GRB.CONTINUOUS if lp else GRB.BINARY
        x = m.addVars(V, lb=0, ub=1, vtype=vtype, name="x")
        y = {}
        for (u, v), _ in E.items():
            if u < v:
                y[u, v] = m.addVar(lb=0, ub=1, vtype=vtype, name=f"y[{u},{v}]")
        for l in K:
            m.addConstr(gp.quicksum(x[v] for v in layer_vertices[l]) == 1, name=f"assign_{l}")
        k = len(K)
        incident = {r: [] for r in V}
        for u, v in y:
            incident[u].append(y[u, v])
            incident[v].append(y[u, v])
        for r in V:
            m.addConstr(gp.quicksum(incident[r]) == (k - 1) * x[r], name=f"star_{r}")
        m.setObjective(gp.quicksum(route_cost[r] * x[r] for r in V) + gp.quicksum(E[(u, v)] * y[u, v] for u, v in y), GRB.MINIMIZE)
        return m

    if model_name == "Q":
        if lp:
            raise ValueError("LP relaxation is not available for Q")
        m = gp.Model("Q", env=env)
        x = m.addVars(V, vtype=GRB.BINARY, name="x")
        for l in K:
            m.addConstr(gp.quicksum(x[v] for v in layer_vertices[l]) == 1, name=f"assign_{l}")
        add_clique_constraints_gurobi(gp, m, x, clique_type, V, anti_edges, layers)
        obj = gp.quicksum(route_cost[r] * x[r] for r in V)
        for (u, v), cost in E.items():
            if u < v:
                obj += cost * x[u] * x[v]
        m.setObjective(obj, GRB.MINIMIZE)
        return m

    if model_name == "GW":
        m = gp.Model("GW", env=env)
        vtype = GRB.CONTINUOUS if lp else GRB.BINARY
        x = m.addVars(V, lb=0, ub=1, vtype=vtype, name="x")
        z = {}
        for (u, v), _ in E.items():
            if u < v:
                z[u, v] = m.addVar(lb=0, ub=1, vtype=GRB.CONTINUOUS, name=f"z[{u},{v}]")
        for l in K:
            m.addConstr(gp.quicksum(x[r] for r in layer_vertices[l]) == 1, name=f"assign_{l}")
        add_clique_constraints_gurobi(gp, m, x, clique_type, V, anti_edges, layers)
        for u, v in z:
            m.addConstr(x[u] + x[v] - z[u, v] <= 1, name=f"gw_{u}_{v}")
        m.setObjective(gp.quicksum(route_cost[r] * x[r] for r in V) + gp.quicksum(E[(u, v)] * z[u, v] for u, v in z), GRB.MINIMIZE)
        return m

    if model_name in {"G", "G+"}:
        strengthened = model_name == "G+"
        m = gp.Model("Gplus" if strengthened else "G", env=env)
        vtype = GRB.CONTINUOUS if lp else GRB.BINARY
        x = m.addVars(V, lb=0, ub=1, vtype=vtype, name="x")
        w = m.addVars(V, lb=0, vtype=GRB.CONTINUOUS, name="w")
        if strengthened:
            Dminus, Dplus, fixed_zero = compute_layer_bounds(V, layers, N, E, layer_vertices)
        else:
            Dminus = {r: 0.0 for r in V}
            Dplus = {r: sum(E[(r, s)] for s in N[r]) for r in V}
            fixed_zero = []
        for l in K:
            m.addConstr(gp.quicksum(x[r] for r in layer_vertices[l]) == 1, name=f"assign_{l}")
        add_clique_constraints_gurobi(gp, m, x, clique_type, V, anti_edges, layers)
        for r in fixed_zero:
            m.addConstr(x[r] == 0, name=f"fixed_zero_{r}")
        for r in V:
            m.addConstr(w[r] >= Dminus[r] * x[r], name=f"g_lb_{r}")
            m.addConstr(w[r] >= gp.quicksum(E[(r, s)] * x[s] for s in N[r]) - Dplus[r] * (1 - x[r]), name=f"g_bigM_{r}")
        m.setObjective(gp.quicksum(route_cost[r] * x[r] for r in V) + 0.5 * gp.quicksum(w[r] for r in V), GRB.MINIMIZE)
        return m

    raise ValueError(f"Unknown model: {model_name}")

##############################################################################
# CPLEX/DOCPLEX BUILDERS
##############################################################################

def import_docplex():
    try:
        from docplex.mp.model import Model
        return Model
    except ImportError as exc:
        raise ImportError("CPLEX was requested, but docplex is not installed.") from exc


def add_clique_constraints_cplex(model, x, clique_type, V, anti_edges, layers):
    if clique_type is None:
        return
    if clique_type not in {"a", "b"}:
        raise ValueError("clique_type must be 'a', 'b', 'c', or None")

    if clique_type == "a":
        for u, v in anti_edges:
            model.add_constraint(x[u] + x[v] <= 1, ctname=f"nonedge_{u}_{v}")
        return

    antiN = {r: [] for r in V}
    for u, v in anti_edges:
        antiN[u].append(v)
        antiN[v].append(u)

    n_layers = len(set(layers))
    for r in V:
        if not antiN[r]:
            continue
        rhs = min(len(antiN[r]), n_layers - 1)
        model.add_constraint(model.sum(x[s] for s in antiN[r]) <= rhs * (1 - x[r]), ctname=f"antineigh_{r}")


def build_cplex_model(model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers, lp=False):
    Model = import_docplex()

    if model_name == "S":
        m = Model(name="S")
        x = {r: m.continuous_var(lb=0, ub=1, name=f"x_{r}") if lp else m.binary_var(name=f"x_{r}") for r in V}
        y = {}
        for (u, v), _ in E.items():
            if u < v:
                y[u, v] = m.continuous_var(lb=0, ub=1, name=f"y_{u}_{v}") if lp else m.binary_var(name=f"y_{u}_{v}")
        for l in K:
            m.add_constraint(m.sum(x[v] for v in layer_vertices[l]) == 1, ctname=f"assign_{l}")
        k = len(K)
        incident = {r: [] for r in V}
        for u, v in y:
            incident[u].append(y[u, v])
            incident[v].append(y[u, v])
        for r in V:
            m.add_constraint(m.sum(incident[r]) == (k - 1) * x[r], ctname=f"star_{r}")
        m.minimize(m.sum(route_cost[r] * x[r] for r in V) + m.sum(E[(u, v)] * y[u, v] for u, v in y))
        return m

    if model_name == "Q":
        if lp:
            raise ValueError("LP relaxation is not available for Q")
        m = Model(name="Q")
        x = {r: m.binary_var(name=f"x_{r}") for r in V}
        for l in K:
            m.add_constraint(m.sum(x[v] for v in layer_vertices[l]) == 1, ctname=f"assign_{l}")
        add_clique_constraints_cplex(m, x, clique_type, V, anti_edges, layers)
        obj = m.sum(route_cost[r] * x[r] for r in V)
        for (u, v), cost in E.items():
            if u < v:
                obj += cost * x[u] * x[v]
        m.minimize(obj)
        return m

    if model_name == "GW":
        m = Model(name="GW")
        x = {r: m.continuous_var(lb=0, ub=1, name=f"x_{r}") if lp else m.binary_var(name=f"x_{r}") for r in V}
        z = {}
        for (u, v), _ in E.items():
            if u < v:
                z[u, v] = m.continuous_var(lb=0, ub=1, name=f"z_{u}_{v}")
        for l in K:
            m.add_constraint(m.sum(x[r] for r in layer_vertices[l]) == 1, ctname=f"assign_{l}")
        add_clique_constraints_cplex(m, x, clique_type, V, anti_edges, layers)
        for u, v in z:
            m.add_constraint(x[u] + x[v] - z[u, v] <= 1, ctname=f"gw_{u}_{v}")
        m.minimize(m.sum(route_cost[r] * x[r] for r in V) + m.sum(E[(u, v)] * z[u, v] for u, v in z))
        return m

    if model_name in {"G", "G+"}:
        strengthened = model_name == "G+"
        m = Model(name="Gplus" if strengthened else "G")
        x = {r: m.continuous_var(lb=0, ub=1, name=f"x_{r}") if lp else m.binary_var(name=f"x_{r}") for r in V}
        w = {r: m.continuous_var(lb=0, name=f"w_{r}") for r in V}
        if strengthened:
            Dminus, Dplus, fixed_zero = compute_layer_bounds(V, layers, N, E, layer_vertices)
        else:
            Dminus = {r: 0.0 for r in V}
            Dplus = {r: sum(E[(r, s)] for s in N[r]) for r in V}
            fixed_zero = []
        for l in K:
            m.add_constraint(m.sum(x[r] for r in layer_vertices[l]) == 1, ctname=f"assign_{l}")
        add_clique_constraints_cplex(m, x, clique_type, V, anti_edges, layers)
        for r in fixed_zero:
            m.add_constraint(x[r] == 0, ctname=f"fixed_zero_{r}")
        for r in V:
            m.add_constraint(w[r] >= Dminus[r] * x[r], ctname=f"g_lb_{r}")
            m.add_constraint(w[r] >= m.sum(E[(r, s)] * x[s] for s in N[r]) - Dplus[r] * (1 - x[r]), ctname=f"g_bigM_{r}")
        m.minimize(m.sum(route_cost[r] * x[r] for r in V) + 0.5 * m.sum(w[r] for r in V))
        return m

    raise ValueError(f"Unknown model: {model_name}")

##############################################################################
# SOLVER-INDEPENDENT HELPERS
##############################################################################

def status_name_gurobi(status):
    _, GRB = import_gurobi()
    names = {
        GRB.LOADED: "LOADED",
        GRB.OPTIMAL: "OPTIMAL",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.INF_OR_UNBD: "INF_OR_UNBD",
        GRB.UNBOUNDED: "UNBOUNDED",
        GRB.CUTOFF: "CUTOFF",
        GRB.ITERATION_LIMIT: "ITERATION_LIMIT",
        GRB.NODE_LIMIT: "NODE_LIMIT",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.SOLUTION_LIMIT: "SOLUTION_LIMIT",
        GRB.INTERRUPTED: "INTERRUPTED",
        GRB.NUMERIC: "NUMERIC",
        GRB.SUBOPTIMAL: "SUBOPTIMAL",
        GRB.INPROGRESS: "INPROGRESS",
        GRB.USER_OBJ_LIMIT: "USER_OBJ_LIMIT",
        GRB.WORK_LIMIT: "WORK_LIMIT",
        GRB.MEM_LIMIT: "MEM_LIMIT",
    }
    return names.get(status, str(status))


def fmt(x):
    return f"{x:.2f}" if isinstance(x, (int, float)) else str(x)


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return ""


def compute_lp_gap(ub, lp_value):
    try:
        ub_f = float(ub)
        lp_f = float(lp_value)
        if abs(ub_f) <= EPS:
            return 0.0 if abs(ub_f - lp_f) <= EPS else ""
        return 100.0 * (ub_f - lp_f) / abs(ub_f)
    except Exception:
        return ""


def initialize_summary(summary_file):
    if os.path.exists(summary_file):
        return
    with open(summary_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instance", "solver", "model", "clique",
            "n_vertices", "n_edges", "n_layers",
            "bin_vars", "cont_vars", "constraints",
            "UB", "LB", "gap", "status_mip", "solution_time", "nodes",
            "lp_status", "lp_value", "lp_solution_time", "lp_gap_percent"
        ])


def append_summary(summary_file, row):
    with open(summary_file, "a", newline="") as f:
        csv.writer(f).writerow(row)


def ensure_results_dir(instance_folder):
    results_dir = os.path.join(instance_folder, "results")
    os.makedirs(results_dir, exist_ok=True)
    return results_dir

##############################################################################
# SOLVE ROUTINES
##############################################################################

def build_model(solver, model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers, lp=False):
    if solver == "gurobi":
        return build_gurobi_model(model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers, lp=lp)
    if solver == "cplex":
        return build_cplex_model(model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers, lp=lp)
    raise ValueError("solver must be 'gurobi' or 'cplex'")


def solve_model(solver, model, log_file=None, quiet=False):
    if solver == "gurobi":
        model.Params.TimeLimit = TIME_LIMIT
        if log_file is not None and not quiet:
            model.Params.LogFile = log_file
            model.Params.LogToConsole = 0
            model.Params.OutputFlag = 1
        model.update()
        start = time.time()
        model.optimize()
        elapsed = time.time() - start
        status = status_name_gurobi(model.Status)
        obj = ""
        if model.SolCount > 0:
            obj = model.ObjVal
        bound = ""
        gap = ""
        nodes = ""
        try:
            bound = model.ObjBound
        except Exception:
            pass
        try:
            gap = model.MIPGap
        except Exception:
            pass
        try:
            nodes = int(model.NodeCount)
        except Exception:
            pass
        nbin = sum(1 for v in model.getVars() if v.VType == "B")
        nvars = model.NumVars
        ncont = nvars - nbin
        nconstr = model.NumConstrs
        model.dispose()
        return {"status": status, "obj": obj, "bound": bound, "gap": gap, "nodes": nodes, "time": elapsed,
                "bin_vars": nbin, "cont_vars": ncont, "constraints": nconstr}

    if solver == "cplex":
        model.parameters.timelimit = TIME_LIMIT
        try:
            model.parameters.threads = 1
        except Exception:
            pass
        start = time.time()
        if log_file is not None and not quiet:
            with open(log_file, "w") as logfile:
                sol = model.solve(log_output=logfile)
        else:
            sol = model.solve(log_output=False)
        elapsed = time.time() - start
        details = model.solve_details
        status = str(details.status)
        obj = ""
        if sol is not None:
            obj = sol.objective_value
        bound = ""
        gap = ""
        nodes = ""
        try:
            bound = details.best_bound
        except Exception:
            pass
        try:
            gap = details.mip_relative_gap
        except Exception:
            pass
        try:
            nodes = details.nb_nodes_processed
        except Exception:
            pass
        try:
            nbin = model.number_of_binary_variables
        except Exception:
            nbin = ""
        try:
            nvars = model.number_of_variables
            ncont = nvars - nbin if isinstance(nbin, int) else ""
        except Exception:
            ncont = ""
        try:
            nconstr = model.number_of_constraints
        except Exception:
            nconstr = ""
        model.end()
        return {"status": status, "obj": obj, "bound": bound, "gap": gap, "nodes": nodes, "time": elapsed,
                "bin_vars": nbin, "cont_vars": ncont, "constraints": nconstr}

    raise ValueError("solver must be 'gurobi' or 'cplex'")


def solve_lp_value(solver, model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers):
    if model_name == "Q":
        return {"status": "NOT_AVAILABLE", "obj": "", "time": ""}
    lp_model = build_model(solver, model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers, lp=True)
    result = solve_model(solver, lp_model, quiet=True)
    return {"status": result["status"], "obj": result["obj"], "time": result["time"]}


def run_formulation(instance_folder, model_name, clique_type, solver):
    basename = os.path.basename(instance_folder.rstrip(os.sep))
    parent_folder = os.path.dirname(instance_folder.rstrip(os.sep))
    summary_file = os.path.join(parent_folder, "summary.csv")
    initialize_summary(summary_file)

    n, edges, layers, route_cost, edge_cost = read_instance(instance_folder)
    V = list(range(n))
    K, layer_vertices, E, N, anti_edges = build_graph(edges, layers, edge_cost)

    if is_layer_wise_complete(anti_edges) or clique_type == "c":
        clique_type = None

    results_dir = ensure_results_dir(instance_folder)
    suffix = f"{solver}_{model_name}"
    if clique_type is not None:
        suffix += "_" + clique_type
    mip_log_file = os.path.join(results_dir, basename + "_" + suffix + ".log")

    lp = solve_lp_value(solver, model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers)

    mip_model = build_model(solver, model_name, V, K, layer_vertices, E, N, anti_edges, route_cost, clique_type, layers, lp=False)
    mip = solve_model(solver, mip_model, log_file=mip_log_file, quiet=False)

    lp_gap = compute_lp_gap(mip["obj"], lp["obj"])

    with open(mip_log_file, "a") as f:
        f.write("\n\n")
        f.write("====================================================\n")
        f.write("TSRSP RESULTS\n")
        f.write("====================================================\n")
        f.write(f"INSTANCE     : {basename}\n")
        f.write(f"SOLVER       : {solver}\n")
        f.write(f"MODEL        : {model_name}\n")
        f.write(f"CLIQUE       : {clique_type}\n")
        f.write("\n")
        f.write(f"N_VERTICES   : {n}\n")
        f.write(f"N_EDGES      : {len(edges)}\n")
        f.write(f"N_LAYERS     : {len(K)}\n")
        f.write("\n")
        f.write(f"BIN_VARS     : {mip['bin_vars']}\n")
        f.write(f"CONT_VARS    : {mip['cont_vars']}\n")
        f.write(f"CONSTRAINTS  : {mip['constraints']}\n")
        f.write("\n")
        f.write(f"MIP_STATUS   : {mip['status']}\n")
        f.write(f"UB           : {fmt(mip['obj'])}\n")
        f.write(f"LB           : {fmt(mip['bound'])}\n")
        f.write(f"MIP_GAP      : {fmt(mip['gap'])}\n")
        f.write(f"MIP_TIME     : {fmt(mip['time'])}\n")
        f.write(f"NODES        : {mip['nodes']}\n")
        f.write("\n")
        f.write(f"LP_STATUS    : {lp['status']}\n")
        f.write(f"LP_VALUE     : {fmt(lp['obj'])}\n")
        f.write(f"LP_TIME      : {fmt(lp['time'])}\n")
        f.write(f"LP_GAP_%     : {fmt(lp_gap)}\n")

    append_summary(summary_file, [
        basename, solver, model_name, clique_type,
        n, len(edges), len(K),
        mip["bin_vars"], mip["cont_vars"], mip["constraints"],
        mip["obj"], mip["bound"], mip["gap"], mip["status"], mip["time"], mip["nodes"],
        lp["status"], lp["obj"], lp["time"], lp_gap
    ])

##############################################################################
# MAIN
##############################################################################

if __name__ == "__main__":

    HELP = f"""
    ======================================================================
    TSRSP SOLVER
    ======================================================================
    
    USAGE
    
        python run_TSRSP.py INSTANCE_FOLDER MODEL [CLIQUE] [SOLVER]
    
    PARAMETERS
    
        INSTANCE_FOLDER
            Path to the instance directory.
    
        MODEL
            One of:
    
                S      : Sama et al. formulation
                Q      : Binary Quadratic formulation
                GW     : Glover-Woolsey formulation
                G      : Glover formulation
                G+     : Strengthened G formulation
                all    : Run all MIP formulations, solving LP first when available
    
        CLIQUE
            Only for Q, GW, G and G+.
            Ignored for S.
    
            a : Non-edge constraints
            b : Anti-neighborhood constraints
            c : No clique constraints for layer-wise complete instances
    
        SOLVER
            Optional.
    
            gurobi : use Gurobi through gurobipy (default)
            cplex  : use CPLEX through docplex
    
    OUTPUT
    
        Solver MIP logs are written in:
    
            INSTANCE_FOLDER/results/scenario_x_SOLVER_MODEL[_CLIQUE].log
    
        The summary file is written in the parent folder:
    
            summary.csv
    
    TIME LIMIT
    
        LP and MIP models are both solved with:
    
            TimeLimit = {TIME_LIMIT} seconds
    
    ======================================================================
    """

    if len(sys.argv) == 1 or sys.argv[1] in ["-h", "--help", "help"]:
        print(HELP)
        sys.exit(0)

    if len(sys.argv) < 3:
        print(HELP)
        sys.exit(1)

    folder = sys.argv[1]
    formulation = sys.argv[2]

    clique = None
    solver = "gurobi"

    if len(sys.argv) >= 4:
        third = sys.argv[3].lower()
        if third in {"gurobi", "cplex"}:
            solver = third
        else:
            clique = third

    if len(sys.argv) >= 5:
        solver = sys.argv[4].lower()

    if solver not in {"gurobi", "cplex"}:
        raise ValueError("SOLVER must be either 'gurobi' or 'cplex'")
     
    print("\n")
    formulation = formulation.upper() if formulation != "G+" else "G+"

    if formulation == "ALL":
        n, edges, layers, route_cost, edge_cost = read_instance(folder)
        K, layer_vertices, E, N, anti_edges = build_graph(edges, layers, edge_cost)
        complete = is_layer_wise_complete(anti_edges) or clique == "c"

        if complete:
            all_models = [("S", None), ("Q", None), ("GW", None), ("G", None), ("G+", None)]
        else:
            all_models = [
                ("S", None),
                ("Q", "a"), ("Q", "b"),
                ("GW", "a"), ("GW", "b"),
                ("G", "a"), ("G", "b"),
                ("G+", "a"), ("G+", "b")
            ]
        
        for model_name, clique_type in all_models:
            print(f"===== RUNNING {solver.upper()} {model_name} {clique_type} =====\n")
            run_formulation(folder, model_name, clique_type, solver)
            print("> DONE\n")
    else:
        if formulation not in {"S", "Q", "GW", "G", "G+"}:
            raise ValueError("MODEL must be one of S, Q, GW, G, G+, all")
        print(f"===== RUNNING {solver.upper()} {formulation} {clique} =====\n")
        run_formulation(folder, formulation, None if formulation == "S" else clique, solver)
        print("> DONE\n")