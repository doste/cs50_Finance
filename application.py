import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    
    # la tabla de index.html muestra: Stock, Quantity, CurrentPrice y TotalValue, asique le paso eso al template

    # primero pido a la DB las stocks que tenga el user, agrupando por symbol. Es decir, si compro 2 de NFLX, y al otro dia 3 mas. Todo eso lo paso como 5 shares (y lo ordeno por fecha)
    #user_symbols = db.execute("SELECT symbol FROM stocks WHERE user_id = :user_id GROUP BY symbol ORDER BY date", user_id = session["user_id"]) 

    user_symbols = db.execute("SELECT symbol FROM stocks WHERE user_id = :user_id", user_id = session["user_id"]) 

    #ahora le pido ala DB la cantidad de cada una de esas stocks:
        #user_quantitis = db.execute("SELECT SUM(quantity) FROM transactions WHERE user_id = :user_id GROUP BY symbol ORDER BY date", user_id = session["user_id"])

    # ahora miro los current price de las shares que tenga el user
    #current_prices_of_user_share = lookup()

    # para pasarle toda esa info a index.html primero construyo una list de dicts con info de cada stock, y directamente le paso esa list:
    user_stock_info = []

    grand_total = 0.0

    for user_symbol in user_symbols:

        quantity = db.execute("SELECT quantity FROM stocks WHERE user_id = :user_id AND symbol = :symbol", user_id = session["user_id"], symbol = user_symbol["symbol"])
        #quantity = db.execute("SELECT SUM(quantity) FROM stocks WHERE user_id = :user_id GROUP BY symbol HAVING symbol = :symbol", user_id = session["user_id"], symbol = user_symbol["symbol"])
        #quantity = quantity[0]['SUM(quantity)']
        quantity = quantity[0]['quantity']
        current_price = lookup(user_symbol["symbol"])["price"]
        total = quantity * current_price

        user_stock_info.append({ 'symbol' : user_symbol["symbol"],
                                    'name' : lookup(user_symbol["symbol"])["name"],
                                    'quantity' : quantity ,
                                    'current_price' : current_price,
                                    'total' : float("{:.2f}".format(total))
                                })
        grand_total = grand_total + total

    #print(f"grand_total ACA : {grand_total}")

    #a index.html tambien deberia pasarle la cash del user, para eso se la pido a la DB
    user_cash = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id = session["user_id"])
    #print(user_cash)
    #user_cash = float("{:.2f}".format(user_cash[0]['cash']))
    user_cash = user_cash[0]['cash']
    #print(f"user_cash : {user_cash}")
    

    grand_total = grand_total + float(user_cash)
    #grand_total = float("{:.2f}".format(grand_total))

    #print(f"grand_total ALLA : {grand_total}")

    #print(user_stock_info)
    return render_template("index.html",  user_stock_info = user_stock_info, user_cash = usd(user_cash), grand_total = usd(grand_total) )


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    # tanto en buy() como en sell() voy a estar modificando la Table transactions, 
    # en este caso, cada vez que se efectue una compra, voy a agregarla a dicha Table

    user_id = session["user_id"]

    if request.method == "POST":

        symbol_to_buy = request.form.get("symbol").upper()

        if not symbol_to_buy:
            return apology("must provide symbol", 403)

        if not lookup(symbol_to_buy):
            return apology("invalid symbol", 403)

        # me guardo cuantas shares quiere comprar el user
        number_of_shares = int(request.form.get("shares"))

        if number_of_shares <= 0 :
            flash("Number of shares must be a positive integer", "danger")
            return redirect(url_for("buy"))
            #return apology("number of shares must be a positive integer", 403)

        # miro cuanta plata disponible tiene el user
        cash_available = db.execute("SELECT cash FROM users WHERE id = :id", id = user_id)
        # esto me devuelve algo asi: [{'cash' : 15900}] asique:
        cash_available = cash_available[0]['cash']

        # miro el precio de la stock
        stock_info = lookup(symbol_to_buy)
        stock_price = stock_info["price"]

        # calculo cuanto le saldria la compra
        purchase_total = number_of_shares * stock_price

        # chequeo que el user tiene suficiente plata para comprar esa cantidad de shares
        if cash_available >= purchase_total :

            # efectuo la compra:

            # chequeo si el user ya posee stock con ese symbol:
            stock_db = db.execute("SELECT * FROM stocks WHERE user_id = :user_id AND symbol = :symbol",
                            user_id=user_id, symbol=symbol_to_buy)
            # esta llamada de aca arriba me puede devolver: Nada (por que el user no posee shares de ese symbol) o UN solo elemento, que detalle que el user sí tiene shares 
            # (un solo elemento porque nunca podria haber mas de uno con el mismo symbol y mismo user justamente por el chequeo que estoy haciendo aca)
            # si ya tiene de ese symbol, solo actualizo la Table (no agrego una nueva row)
            if len(stock_db) == 1:

                # efectuar la compra significa actualizar la 'quantity' de esa stock del user,
                # para eso, calcula la nueva 'quantity' sumando la 'quantity' que ya tenia + la nueva que está comprando
                new_quantity = int(stock_db[0]["quantity"]) + number_of_shares

                db.execute("UPDATE stocks SET quantity = :quantity WHERE user_id = :user_id AND symbol = :symbol", quantity = new_quantity,
                                                                                                                        user_id = user_id,
                                                                                                                        symbol = symbol_to_buy)
            else:
                # en cambio, si el user NO poseia ninguna shares de este symbol, entonces inserto de cero una nueva row 
                db.execute("INSERT INTO stocks (user_id, symbol, quantity, price_per_share) VALUES(:user_id, :symbol, :quantity, :price_per_share)", user_id = user_id,
                                                                                                                                                    symbol = symbol_to_buy,
                                                                                                                                                    quantity = number_of_shares, 
                                                                                                                                                    price_per_share = stock_price)


            # ademas de modificar la Table stocks, actualizo la Table users, descontale la cash de la compra realizada
            cash_after_purchase = cash_available - purchase_total

            db.execute("UPDATE users SET cash = :cash WHERE id = :user_id", cash = cash_after_purchase, user_id = user_id)


            # por ultima agrego la compra a la Table transactions (le paso : user_id , stock_id, price_per_share, quantity y type)

            #primero le pido a la Table stocks el ID del stock que el user está comprando:
            stock_id = db.execute("SELECT id FROM stocks WHERE user_id = :user_id AND symbol = :symbol", user_id = user_id,
                                                                                                       symbol = symbol_to_buy)
            stock_id = stock_id[0]['id']

            db.execute("INSERT INTO transactions (user_id, stock_id, price_per_share, quantity, type) VALUES(:user_id, :stock_id, :price_per_share, :quantity, 'BUY')",
                                                                                                                                                                         user_id = user_id,
                                                                                                                                                                        stock_id = stock_id,
                                                                                                                                                                        price_per_share = stock_price,
                                                                                                                                                                        quantity = number_of_shares)

        else:
            flash("Sorry. You can't afford the number of shares at the current price", "danger")
            return redirect(url_for("buy"))
            #return apology("Sorry. You can't afford the number of shares at the current price", 403)


        #chequeo que se desconto la plata
        #platika = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id = session["user_id"])
        #cash_to_show = float("{:.2f}".format(platika[0]["cash"]))
        #return render_template("auxBuy.html", cash=cash_to_show )

        flash("Purchase successfull", "success")

        return redirect(url_for("index"))

    elif request.method == "GET":
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    user_id = session["user_id"]
    # teniendo la Table transactions, le paso toda esa info a history.html

    # primero me construyo una lista de dicts, donde le guardo 'de forma bonita' toda la info para pasarsela:
    # lo que va a terminar mostrando history.html es algo asi:
    # [ TYPE OF TRANSACTION  |  STOCK SYMBOL  |  PRICE PER SHARE  |  NUMBER OF SHARES  |  DATE ]
    # asique me armo una lista con dicts con todos esos datos

    #para cada transaction que haya en la Table transactions creo un dict y lo agrego a la lista

    dict_of_transactions = db.execute("SELECT stock_id, type, price_per_share, quantity FROM transactions WHERE user_id = :user_id", user_id = user_id)
    
    # de este dict obtengo el Type y el stock_id, con el cual accedo a la Table stocks para ver la info sobre ese stock en particular

    list_of_transactions= []

    # de la Table stocks voy a querer: el symbol, el price, el number of shares y la date
    # por cada transaction que haya en dict_of_transactions, le pido a la Table stocks info usando el stock_id
    # y asi me armo una lista de dicts, en cada dict tendré toda la info sobre esa transaction
    for transaction in dict_of_transactions:
        stock_id = transaction['stock_id']
        dict_of_stocks = db.execute("SELECT symbol, quantity, price_per_share, date FROM stocks WHERE id = :stock_id AND user_id = :user_id", stock_id = stock_id, user_id = user_id) #esto me devuelve una sola transaction (le paso el id, el cual es unico)
        if dict_of_stocks :
            transaction_type = transaction['type']
            transaction_symbol = dict_of_stocks[0]['symbol']
            transaction__price_per_share = transaction['price_per_share']
            transaction_quantity = transaction['quantity']
            transaction_date = dict_of_stocks[0]['date']
            transactions_aux_dict = { 'type' : transaction_type,
                                     'symbol' : transaction_symbol,
                                     'price_per_share' : transaction__price_per_share,
                                     'number_of_shares' : transaction_quantity,
                                     'date' : transaction_date } 
            list_of_transactions.append(transactions_aux_dict)



    
        print(list_of_transactions)
   

    return render_template("history.html", list_of_transactions= list_of_transactions)




@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect(url_for("index"))
        #return redirect(url_for("avisarRegistrado", id = session["user_id"], username = request.form.get("username")))

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":

        # me aseguro que me pasen un symbol
        if not request.form.get("symbol"):
            return apology("must enter symbol to look up", 403)

        # llamo a lookup pasandole el symbol submiteado, esta me devolvera un dict (con name, stock price y symbol), este dict se lo paso a quoted.html
        stock_info = lookup(request.form.get("symbol"))

        return render_template("quoted.html", stock_info = stock_info)

    elif request.method == "GET":

        return render_template("quote.html")

#@app.route("/registered")
#def avisarRegistrado():
#    return render_template("auxYouAreRegistered.html", id = session["user_id"])

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide password", 403)

        # Aseguro que el username no exista ya:
        # miro la DB a ver si existe alguna row con ese username
        rows = db.execute("SELECT * FROM users WHERE username = :username", username = request.form.get("username"))
        if len(rows) != 0:
            return apology("username already exists. Choose a different one", 403)


        # Ensure password was submitted
        if not request.form.get("password") or not request.form.get("confirmation"):
            return apology("must provide password", 403)

        # aseguro que las password matchean
        if request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords don't match", 403)

        # genero el password hash para insertarlo en la DB
        password_hash = generate_password_hash(request.form.get("password"), "sha256")

        #agrego el user a la DB
        db.execute("INSERT INTO users (username, hash) VALUES(:username, :hash)", username = request.form.get("username"), hash = password_hash)

        # login user automatically and remember session
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect(url_for("index"))
        #return redirect(url_for("avisarRegistrado"))

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")




@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    # tanto en buy() como en sell() voy a estar modificando la Table transactions, 
    # en este caso, cada vez que se efectue una venta, voy a agregarla a dicha Table

    user_id = session["user_id"]

    # los stocks que posee el user lo voy a usar en cada rama del if, por lo tanto lo calculo aca afuera:

    # le pido a la DB el dictionary con todos los symbols que ownea el user
    dict_of_symbols = db.execute("SELECT symbol FROM stocks WHERE user_id = :user_id GROUP BY symbol", user_id = user_id )
    # esto de aca arriba me devolveria algo asi: [{'symbol' : NFLX}, {'symbol' : AAPL}, {'symbol' : TSLA }]
    #print(f"dict_of_symbols = {dict_of_symbols} ")

    # me armo una lista, donde solo esten los symbols
    symbols_owned_by_user = []

    for symbol in dict_of_symbols:
        symbols_owned_by_user.append(symbol["symbol"])
    # en cambio, ahora symbols_owned_by_user  me devuelve algo asi : ['NFLX', 'AAPL', 'TSLA']
    #print(f"symbols_owned_by_user = {symbols_owned_by_user} ")

    if request.method == "POST":

        symbol_to_sell = request.form.get("symbol").upper()

        if symbol_to_sell not in symbols_owned_by_user:
            return apology("you don't own any stock with this symbol", 407)

        if not symbol_to_sell:
            return apology("must select a stock", 407)

        shares_to_sell = float(request.form.get("shares"))

        if shares_to_sell <= 0 :
            return apology("must provide valid number of shares", 407)

        # me fijo que el user posea la cantidad de shares que desea vender:
        # le pido a la DB cuantas shares tiene el user
        shares_quantity = db.execute("SELECT SUM(quantity) FROM stocks WHERE user_id = :user_id AND symbol = :symbol_to_sell", user_id = user_id , symbol_to_sell = symbol_to_sell)
        # la DB me devuelve algo asi: [{'SUM(quantity)': 1}], asique tengo que accederlo asi:
        shares_owned = shares_quantity[0]['SUM(quantity)']

        if shares_to_sell > shares_owned :
            return apology("you don't have that many shares", 407)
        else:
            # efectuo la venta:

            # por un lado actualizo la Table stocks:
            # modifico la quantity del user de ese symbol
            new_quantity = shares_owned - shares_to_sell
            db.execute("UPDATE stocks SET quantity = :new_quantity WHERE user_id = :user_id AND symbol = :symbol ", new_quantity = new_quantity, user_id = user_id, symbol = symbol_to_sell)


            # por otro lado, le sumo el valor de la venta a la cash del user:
            # me fijo cuanta cash le corresponde
            share_price = lookup(symbol_to_sell)["price"]
            cash_to_user = shares_to_sell * share_price
            # ahora actualizo la Table users, modificando la cash del user (sumandole a lo que ya tenia esta nueva cantidad)
            user_cash = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id = user_id)
            user_cash = float("{:.2f}".format(user_cash[0]['cash']))

            db.execute("UPDATE users SET cash = :new_cash WHERE id = :user_id", new_cash = user_cash + cash_to_user, user_id = user_id)

            # ademas agrego la venta a la Table transactions (le voy a pasar: user_id , stock_id, price_per_share, quantity y type)

            #primero le pido a la Table stocks el ID del stock que el user está vendiendo:
            stock_id = db.execute("SELECT id FROM stocks WHERE user_id = :user_id AND symbol = :symbol", user_id = user_id,
                                                                                                       symbol = symbol_to_sell)
            stock_id = stock_id[0]['id']

            db.execute("INSERT INTO transactions (user_id, stock_id, price_per_share, quantity, type) VALUES(:user_id, :stock_id, :price_per_share, :quantity, 'SELL')",
                                                                                                                                                                         user_id = user_id,
                                                                                                                                                                        stock_id = stock_id,
                                                                                                                                                                        price_per_share = share_price,
                                                                                                                                                                        quantity = shares_to_sell)

            # por ultimo, si la new_quantity es == 0, directamente le elimino ese stock al user (esto lo hago aca al final pq en el paso anterior necesite acceder al stock que el user esta vendiendo)
            #if new_quantity == 0:
            #   db.execute("DELETE FROM stocks WHERE user_id = :user_id AND symbol = :symbol", user_id = user_id, symbol = symbol_to_sell)
            #  HACER ESTO DE ACA ARRIBA ME ARRUINA EL 'history' , MAS ALLA DE QUE EL USER TENGA 0 SHARES DE UNA STOCK, DEBO SEGUIR TENIENDO ESA REFERENCIA EN LA TABLE stocks PARA MOSTRARLA EN LA history

        flash("Sale successfull", "success")
        
        return redirect(url_for("index"))

    else:
        # a sell.html le tengo que pasar que stocks tiene el user
        return render_template("sell.html", symbols = symbols_owned_by_user)


@app.route("/changepassword", methods=["GET", "POST"])
@login_required
def changepassword():

    user_id = session["user_id"]

    if request.method == "POST":

        # le pido a la DB la password del user, para compararla y confirmar con la 'old_password'
        # lo unico que sabe la DB sobre la password es el hash, asique le pido eso
        hash_password = db.execute("SELECT hash FROM users WHERE id = :user_id", user_id = user_id)
        hash_password = hash_password[0]['hash']

        # lo comparo con la 'old_password' que me está dando el user para confirmar que coinciden

        if not check_password_hash(hash_password, request.form.get("old_password")):
            flash("Invalid password", "danger")
            return redirect(url_for("changepassword"))


         # Ensure password was submitted
        if not request.form.get("old_password") or not request.form.get("new_password"):
            return apology("must provide password", 403)

        # aseguro que las password matchean
        if request.form.get("new_password") != request.form.get("new_password_confirmation"):
            return apology("passwords don't match", 403)

        # aseguro que la nueva password sea distinta
        if request.form.get("new_password") == request.form.get("new_password_confirmation"):
            return apology("passwords don't match", 403)

         # genero el NUEVO password hash para insertarlo en la DB
        new_password_hash = generate_password_hash(request.form.get("new_password"), "sha256")

        # actualizo la Table users modificando el hash 
        db.execute("UPDATE users SET hash = :new_hash WHERE id = :user_id", new_hash = new_password_hash, user_id = user_id)

        flash("Password successfully changed :) ", "success")

        return redirect(url_for("index"))

    elif request.method == "GET":
        return render_template("changepassword.html")

@app.route("/add_funds", methods=["GET", "POST"])
@login_required
def add_funds():

    user_id = session["user_id"]

    if request.method == "POST":

        amount_to_add = int(request.form.get("amount_to_add"))

        if amount_to_add <= 0:
            flash("must provide a valid amount to add", "danger")
            return redirect(url_for("add_funds"))

        # primero le pido a la DB cuanta cash ya tiene el user:
        user_cash = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id = user_id)
        user_cash = user_cash[0]['cash']

        # ahora actualizo la Table, modificando la cash del user (sumandole a lo que ya tenia lo que está agregando ahora)
        new_amount_of_cash = user_cash + amount_to_add

        db.execute("UPDATE users SET cash = :new_amount_of_cash WHERE id = :user_id", new_amount_of_cash = new_amount_of_cash, user_id = user_id)

        flash("Funds added successfully", "success")

        return redirect(url_for("index"))

    elif request.method == "GET":
        return render_template("addfunds.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
