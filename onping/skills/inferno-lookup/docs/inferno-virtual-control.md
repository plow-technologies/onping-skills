
# Inferno: Documentation

Inferno is a functional scripting language.

## Types

A core feature of the Inferno language is its type system. Types in a programming language are a way of labeling all values with the kind of “thing” they represent. For instance, within the Inferno language, there are values which are numeric, textual or represent time/timezones (amonst many others). Types can provide useful information to the user and help prevent many common errors when a script contains a mistake (like adding a boolean to an integer, or passing the wrong parameter to a function). These are some of the types present in Inferno:

- `int`: Integer numbers. These are numbers without decimals.
- `double`: Double-precision floating numbers. These are numbers with decimals.
- `bool`: Truth values. This type has only two members: `#true` and `#false`.
- `epochTime`: Points in time.
- `word16`: Unsigned 16-bit integeres.
- `word32`: Unsigned 32-bit integeres.
- `word64`: Unsigned 64-bit integeres.

Besides these “basic” types, there are several more complex types which can be built up from the types above:

- `array of *`: Where `*` can be `int`, `double` or potentially another array or other complex type
- `series of *`: This type represents the values of a control/virtual parameter. See the `TachDB` module below for functions that help extract values from a series.
- `option of *`: A type such as `option of int` has values that look like `Some 4` or `None` and represents a values which could potentially be undefined. This is useful to indicate a value is missing for a certain time in a time series, for example.
- `* -> *` (function type): A value can also be a function. For instance, a function that takes a `double` and returns an `int` has type `double -> int`.
- `(*, ..., *)` (tuple type): We can bundle several different types into a tuple, useful if we want to return multiple value from a function, for example a function with the type `double -> (int, text)` takes a `double` value and returns both an `int` and a `text` value. The unit/empty tuple `()` can be used to represent no (useful) value is being returned.
- Record types: A record is like a tuple where each field has a name. For instance `{ht = 1.51; wt = 62.4}` is a record value containing two fields `ht` and `wt` . We say such a record has type `{ht: double; wt: double}`.

There is no need to tell the system what type any of the literals and variables are. It can deduce this information automatically and will only warn the user in case of a mistake.

## Syntax

### Literals

Literals are values that you write directly in the script, like `0.8` or `120`.  
There are three kinds of literals:

- Numeric literal (with decimals): `0.80`, `100.0`, etc. They have type `double`.
- Numeric literal (without decimals): `120`, `1234`, etc. They can have type `int` or `double`, depending on context.
- Hexadecimal literal: `0xA9F`, `0x8D01`, etc. They have type `word64`.
- Text/string literal: `"Hello"` They have type `text`.
- Interpolated string: `` `Hello ${23} ${"world"}!` `` They have type `text`.

### Variables

Variables are names that represent values, like `foo` or `bar`. They always start with a letter and are followed by zero or more letters or numbers or underscores. Examples of valid variables are: `x`, `y`, `MyVariable`, `ThisIsAVariable`, `this_2_is_a_variable`, `Year2018`.

### Optionals

Certain functions in the standard library are not guaranteed to return a value. This is indicated by the optional type, which has two values:

- If a value is present, it is written using the `Some` keyword. For example the expression `Some 120` denotes an `option of int`, whereas `Some "Hello world!"` has type `option of text`.
- If a value is missing, we indicate this using the `None` keyword.

### Tuples

Values, variables, and other constructs can be grouped together into tuples, for example, if a function returns multiple values. Tuples are formed by appending values in brackets, e.g. `(0.80, "Hello world!")`, which has the type `(int, text)` . We can also indicate the return of a “unit” value by the unit/empty tuple `()`, not to be confused with the optional value `None`.

### Enums

An enum is a user defined set of names/labels which can be stored inside a control parameter instead of a simple `double` value. Using an enum may be useful if the parameter value represents a discrete state of a system rather than a continuous value, such as pressure or flow rate. For example, the `bool` type is an enum with the labels `#true` and `#false`. Another example of an enum might be a `plungerState` enum, with `#rising`, `#falling` or `#disabled` states. Using enums has multiple advantages described further below, not least of which is better readability of scripts.

### Functions

Like we mentioned earlier (see the Types section), a variable can contain a function. To apply an argument to a function, simply put the argument you want to pass tothe function right after the function variable. For example, if we have a function called `f` of type `double -> bool`, we can apply an argument `3.14` to `f`, simply by writing `f 3.14`. The result will have type `bool`.

You can create your own functions to re-use parts of your code. For example:
```
let square = fun x -> x * x in
(square 3.4, square 4.5)
```

### Let assignments

A let statement can be used to introduce temporary/intermediate values within a script:

```
let x = <code 1> in
<code 2>
```

Let statements can optionally be *annotated* with a type, if you want to tell Inferno what the type of an expression should be. For example, the literal `4` can be either an `int` or a `double`, so you can tell Inferno you mean `int` by:
```
let x : int = 4 in
<code that uses x as an int>
```
### Conditionals

Inferno includes the familiar `if...then...else...` construct. The syntax goes as  
follows:

```
if <boolean expression>
then
    <code 1>
else
    <code 2>
```

Unlike most programming languages, `if` statements in Inferno are expressions. This means we can assign an `if` expression to a variable or pass it to a function:

```
let x = if 2 > 3 then 5 else 6 in
x + 1
```

### Case statements

The `match` statement is like a more powerful `if` statement, which allows us to pattern match not only on `bool`eans but also other enums as well as optional types. The syntax for a `match` is as follows:

```
match <expression> with {
  | <pattern 1> -> 
    <code 1>
  ...
  | <pattern n> ->
    <code n>
}
```

Like the `if` statement, a `match` is also an expression, assignable to a variable, which means all the branches must return a value of the same type. A `match` statement can be used instead of an `if` statement:

```
let x =
  match 2 > 3 with {
    | #true -> 5
    | #false -> 6
  }
in
x + 1
```

It can also be used to inspect the value of an optional type:

```
match latestValue pid1 with {
  | Some val -> val * 2
  | None -> 0
}
```

In this instance, we analyze the result of calling `latestValue pid1`, which may rerturn a `None` value. The branches of a `match` must always be total, namely, we must handle all the cases for any given type, i.e. we must have a `#true` and a `#false` branch for `bool`, a `Some x` and `None` for `option of *`, etc. If we only care about one specific case and want to lump all the other cases into a “catch all” pattern, we can use the wildcard `_` pattern:

```
match someNumber with {
  | 0 -> 1
  | 1 -> 0
  | _ -> 42
}
```

It is also possible to match on multiple values at once with the use of tuples:

```
match (latest pid1, someNumber) with {
  | (Some v, 0) -> v
  | (Some v, 1) -> (-v)
  | (Some _, _) -> 42
  | (None, 0) -> 1
  | (None, 1) -> 0
  |  _         -> 84
}
```

### Assertions

Assertions in scripts can be used to check invariants/assumptions made about the data being processed, e.g.:

```
assert latestTempReading > 0 in
<code>
```

If the assertion is violated during the execution of the script an error is logged.

### Arrays

Arrays can be useful in scripts when pulling data from several virtual/control parameters and aggregating the results. Small arrays can be expressed as array literals:
```
[1.1, 34.5, 1231.53]
```

More complex array can be created using the array builder notation which allow for modifying and filtering arrays. The syntax of array builders is the following:

```
[ <expr> | x1 <- <array 1> , ... xn <- <array n>, (if <boolean condition>) ]
```

The array builder notation allows for filtering of elements

```
[ n | n <- someNumberArray, if n > 10 ]
```

applying a transformation to each element of an array

```
[ 2 * n | n <- someNumberArray ]
```

or combining several arrays by taking their product

```
[ (n, m) | n <- someNumberArray, m <- someOtherArray ]
```

See the `Array` module below for builtin functions that manipulate arrays.

### Records

A record is like a tuple, but it names its fields so that it is easier to distinguish between them or refer to them. For example:
```
let r1 = {ht = 1.51; wt = 62.4} in
let bmi = fun r -> r.wt / (r.ht * r.ht) in
bmi r1
```
In the example above, we create a record `r1` with two fields `ht` and `wt` to represent the height and weight of a person. The `bmi` function is given an arbitrary record `r` and extracts the two fields `ht` and `wt` using the record field access syntax e.g. `r.ht`.

The example above has the following types:

```
r1 : {ht: double; wt: double}
bmi : forall 'a. {ht: double; wt: double; 'a} -> double
```

Here, variable `r1` (which is assigned a record value) has type `{ht: double; wt: double}`, and the type of the function `bmi` uses a type variable `'a` to denote the fact that it accepts as argument any record that has at least the fields `ht` and `wt`.

This allows us to reuse functions operating on records, even when more fields are added. For example, the following code is also correct:
```
let r1 = {ht = 1.51; wt = 62.4} in
let bmi = fun r -> r.wt / (r.ht * r.ht) in
let x1 = bmi r1 in
let r12 = {ht = 1.51; wt = 62.4; name="Zaphod"} in
let x2 = bmi r2 in
...
```

### Predefined operators and precedence

| Precedence | Left          | None        | Right |
| ---------- | ------------- | ----------- | ----- |
| 11         |               |             | **    |
| 10         | *, /, %, .&.  |             |       |
| 9          | +, -, `.XOR.` |             |       |
| 8          | .\|.          |             |       |
| 7          |               | <,>, >=, <= |       |
| 6          |               | ==, !=      |       |
| 5          |               |             | &&    |
| 4          |               |             | XOR   |
| 3          |               |             |       |

Operator precedence and associativity.

## Type Classes

Some functions and operators operate on more than one type. For example, the division operator `/` can work on both `int`s and `double`s. Inferno uses the concept of *type classes* to represent such functions. Internally, `/` is defined as follows:
```
define division on int int int;
define division on int double double;
define division on double int double;
define division on double double double;

(/) : forall 'a 'b 'c. {requires division on 'a 'b 'c} => 'a -> 'b -> 'c := ...
```
Here, `division` is a type class with three type parameters `'a`, `'b`, and `'c`. The first few lines define the possible combinations of three types for which `division` is defined. The type of `/` then says that for any types `'a`, `'b`, and `'c` for which `division` is defined, `/` can be a function with type `'a -> 'b -> 'c`.

For example, if we divide an `int` by an `int`, this says that the result will also be an `int`. Similarly, if we divide a `double` by an `int`, the result will be a `double`.

An auto-generated list of all type classes and the list of types for which they are defined is at the bottom of this document.

## Modules

Modules are a way of organizing reusable functions/scripts into units which another script can depend on and import. The standard library provides several modules, which are detailed below. If a module `Foo` has a function `bar`, then you can use it in your script by writing `Foo.bar`.

If you find you are using functions from a module repeatedly in a script, you can also "open" the module and make its functions available to use without a prefix:
```
open Foo in
<your script here that can say just bar instead of Foo.bar>
```
Alternatively, you can rename a module using a `let module` statement:
```
let module F = Foo in
<your script here that can say F.bar instead of Foo.bar>
```

### Module Base (needs no prefix)

#### `! : forall 'a. {requires bitlike on 'a} ⇒ 'a → 'a`
Complements (switches 0s and 1s) all bits in the argument

----

#### `- : forall 'a. {requires negate on 'a} ⇒ 'a → 'a`
Negation (unary) on `int`, `double`, or `timeDiff`

----

#### `None : forall 'a. option of 'a`
Optional type, representing a value which may be undefined.
`None` indicates no value is present and `Some v` holds a value `v`
   To test whether an optional `o` holds some value, use `match ... with` and pattern match on `o`:
~~~
match o with {
  | Some v -> // use v here
  | None -> // handle the case where o is None
}
~~~

----

#### `Some : forall 'a. 'a → option of 'a`
Optional type, representing a value which may be undefined.
`None` indicates no value is present and `Some v` holds a value `v`
   To test whether an optional `o` holds some value, use `match ... with` and pattern match on `o`:
~~~
match o with {
  | Some v -> // use v here
  | None -> // handle the case where o is None
}
~~~

----

#### `abs : forall 'a. {requires abs on 'a} ⇒ 'a → 'a`
Absolute value (sometimes written |x|) on `int`, `double`, or `timeDiff`

----

#### `arcCos : double → double`
Inverse cosine (trigonometric function) of a `double`

----

#### `arcSin : double → double`
Inverse sine (trigonometric function) of a `double`

----

#### `arcTan : double → double`
Inverse tan (trigonometric function) of a `double`

----

#### `ceiling : forall 'a. {requires roundable on 'a} ⇒ 'a → int`
Ceiling function (rounds up to nearest integer)

----

#### `clearBit : forall 'a. {requires bitlike on 'a} ⇒ 'a → int → 'a`
Clears the bit at the provided offset (i.e., sets it to `0`)

----

#### `complementBit : forall 'a. {requires bitlike on 'a} ⇒ 'a → int → 'a`
Switches the bit at the provided offset (`0` to `1` or vice versa)

----

#### `cos : double → double`
Cosine (trigonometric function), on `double`

----

#### `cosh : double → double`
Hyperbolic cosine (trigonometric function) of a `double`

----

#### `doubleToInt : double → int`
Convert double to int

----

#### `exp : double → double`
Exponential function

----

#### `floor : forall 'a. {requires roundable on 'a} ⇒ 'a → int`
Floor function (rounds down to nearest integer)

----

#### `fromBCD : word64 → option of word64`
Decode a BCD-encoded word64

----

#### `fromOption : forall 'a. 'a → option of 'a → 'a`
The `fromOption` function unwraps an optional value, if given a default value to fall back on in case the value of the optional is `None`.
  ~~~inferno
  fromOption "hi" (Some "hello") == "hello"
  fromOption "hi" None == "hi"
  ~~~

----

#### `fromWord : forall 'a. {requires fromWord on 'a} ⇒ 'a → int`
Convert a word to an `int`

----

#### `fst : forall 'a 'b. ('a, 'b) → 'a`
Gets the first component of a tuple: `fst (x, y) == x`

----

#### `id : forall 'a. 'a → 'a`
The identity function

----

#### `intToDouble : int → double`
Convert int to double

----

#### `latestValue : forall 'a. {implicit now : time} ⇒ series of 'a → option of 'a`
Returns the latest value of the parameter, if one exists.

----

#### `latestValueAndTime : forall 'a. {implicit now : time} ⇒ series of 'a → option of ('a, time)`
Returns the latest value of the parameter (and the corresponding timestamp), if one exists.

----

#### `latestValueAndTimeBefore : forall 'a. time → series of 'a → option of ('a, time)`
Returns the latest value of the parameter (and the corresponding timestamp) before the given time, if one exists.

----

#### `latestValueBefore : forall 'a. time → series of 'a → option of 'a`
Returns the latest value of the parameter before the given time, if one exists.

----

#### `limit : double → double → double → double`
`limit l u x = min l (max x u)` limits `x` to be between `l` and `u`

----

#### `ln : double → double`
Natural logarithm

----

#### `log : double → double`
Logarithm with base `10`

----

#### `logBase : double → double → double`
Logarithm with base `b`

----

#### `max : forall 'a. {requires order on 'a} ⇒ 'a → 'a → 'a`
Maximum function on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `min : forall 'a. {requires order on 'a} ⇒ 'a → 'a → 'a`
Minimum function on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `pi : double`
Pi (`3.14159... :: double`), the constant

----

#### `random : () → double`
A (pseudo)random `double` number in the `[0, 1)` interval. To obtain a random number between 20 and 30, use `(10 * random ()) + 20`. The `()` argument is needed so that each time `random` is called a new random value is generated.

----

#### `recip : double → double`
Reciprocal fraction

----

#### `resolutionToInt : resolution → int`


----

#### `round : forall 'a. {requires roundable on 'a} ⇒ 'a → int`
`round x` returns the nearest integer to `x`
  (the even integer if `x` is equidistant between two integers)

----

#### `roundTo : int → double → double`
`roundTo d x` rounds `x` to `d` decimal places

----

#### `setBit : forall 'a. {requires bitlike on 'a} ⇒ 'a → int → 'a`
Sets the bit at the provided offset to `1`

----

#### `shift : forall 'a. {requires bitlike on 'a} ⇒ 'a → int → 'a`
`shift x i` shifts `x` left by `i` bits if `i` is positive, or right by `-i` bits otherwise.  Right shifts perform sign extension on signed number types (i.e. they fill the top bits with `1` if `x` is negative and with `0` otherwise).
  Examples:
  ~~~inferno
  shift 0x0F0 4 == 0xF00
  shift 0x0F0 (-4) == 0x00F
  shift 0x0F0 (-8) == 0x000
  ~~~

----

#### `sin : double → double`
Sine (trigonometric function) of a `double`

----

#### `sinh : double → double`
Hyperbolic sine (trigonometric function) of a `double`

----

#### `snd : forall 'a 'b. ('a, 'b) → 'b`
Gets the second component of a tuple: `snd (x, y) == y`

----

#### `sqrt : double → double`
Square root

----

#### `tan : double → double`
Tan (trigonometric function), on `double`

----

#### `tanh : double → double`
Hyperbolic tangent (trigonometric function) of a `double`

----

#### `testBit : forall 'a. {requires bitlike on 'a} ⇒ 'a → int → bool{#false,#true}`
Checks if the bit at the provided offset is set

----

#### `toBCD : word64 → word64`
Encode a BCD-encoded word64

----

#### `toResolution : int → resolution`


----

#### `toWord16 : forall 'a. {requires toWord16 on 'a} ⇒ 'a → word16`
Convert an `int` or another word to a `word16`, dropping bits if necessary

----

#### `toWord32 : forall 'a. {requires toWord32 on 'a} ⇒ 'a → word32`
Convert an `int` or another word to a `word32`, dropping bits if necessary

----

#### `toWord64 : forall 'a. {requires toWord64 on 'a} ⇒ 'a → word64`
Convert an `int` or another word to a `word64`

----

#### `truncate : forall 'a. {requires roundable on 'a} ⇒ 'a → int`
`truncate x` returns the integer nearest `x` between zero and `x`

----

#### `truncateTo : int → double → double`
`truncateTo d x` truncates `x` to `d` decimal places

----

#### `valueAt : forall 'a. {implicit resolution : resolution} ⇒ series of 'a → time → option of 'a`
Returns the value of the parameter in the chunk containing the given time, if it exists.
  For example, if resolution is 128 (thus chunks are 0-127, 128-255, 256-383, ...), and the parameter `p` has values:
  ~~~
  V:       1.0        |           |        3.0        |
  T: 0 ... 120 ... 127 128 ... 255 256 ... 300 ... 383 384 ...
  ~~~
  then:
  ~~~inferno
  open Time in
  valueAt p (toTime (seconds 128)) == Some 1.0
  valueAt p (toTime (seconds 129)) == None
  valueAt p (toTime (seconds 380)) == Some 3.0
  ~~~

----

#### `valueAtOrAdjacent : forall 'a. {implicit resolution : resolution} ⇒ series of 'a → time → option of 'a`
Returns the value of the parameter in the chunk containing the given time, if it exists, or in the closest adjacent chunk (previous or next chunk), if it exists.
  For example, if resolution is 128 (thus chunks are 0-127, 128-255, 256-383, ...), and the parameter `p` has values:
  ~~~
  V:       1.0        |           |        3.0        |4.0
  T: 0 ... 120 ... 127 128 ... 255 256 ... 300 ... 383 384 ...
  ~~~
  then:
  ~~~inferno
  open Time in
  valueAtOrAdjacent p (toTime (seconds 380)) == Some 3.0  // value from current chunk
  valueAtOrAdjacent p (toTime (seconds 130)) == Some 1.0  // value from previous chunk
  valueAtOrAdjacent p (toTime (seconds 200)) == Some 3.0  // value from next chunk
  valueAtOrAdjacent p (toTime (seconds 1024)) == None
  ~~~

----

#### `valuesBetween : forall 'a. {implicit resolution : resolution} ⇒ series of 'a → time → time → array of ('a, time)`
Returns all values between two times, using the implicit resolution.
  If the resolution is set to 1, this returns all the events (actual values, not approximations) in the given time window.

----

#### `zip : forall 'a 'b. array of 'a → array of 'b → array of ('a, 'b)`
Zip two arrays into a array of tuples/pairs. If one input array is shorter than the other, excess elements of the longer array are discarded. `zip [1, 2] ['a', 'b'] == [(1,'a'),(2,'b')]`

----

#### `zipWith : forall 'a 'b 'c. ('a → 'b → 'c) → array of 'a → array of 'b → array of 'c`
`zipWith f xs ys` zips two arrays together by applying the pair-wise
  function `f` to corresponding elements. If one input array is shorter than the
  other, excess elements of the longer array are discarded.
  Example: `zipWith (+) [1, 2, 3] [4, 5, 6] == [5, 7, 9]`

----

#### `(!!) : forall 'a. array of 'a → int → 'a`
Array indexing: an infix operator to get the ith element of an array. Throws a RuntimeError if i is out of bounds.

----

#### `(!=) : forall 'a. 'a → 'a → bool{#false,#true}`
The (not) equals function works on any value of the same type. Always returns `#true` for functions

----

#### `(!?) : forall 'a. array of 'a → int → option of 'a`
Safe array indexing: an infix operator to get the ith element of an array. Returns None if i is out of bounds.

----

#### `(%) : int → int → int`
Modulus operator. `n % m` is the remainder obtained when `n` is divided by `m`. E.g. `5 % 3 == 2`

----

#### `(&&) : forall 'a. {requires bitlike on 'a} ⇒ 'a → 'a → 'a`
Bitwise AND

----

#### `(*) : forall 'a 'b 'c. {requires multiplication on 'a 'b 'c} ⇒ 'a → 'b → 'c`
Multiplication on `int`, `double`

----

#### `(**) : forall 'a. {requires power on 'a} ⇒ 'a → 'a → 'a`
`x ** y` raises `x` to the power of `y`, where the arguments are `int` or `double`

----

#### `(+) : forall 'a 'b 'c. {requires addition on 'a 'b 'c} ⇒ 'a → 'b → 'c`
Addition on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `(-) : forall 'a 'b 'c. {requires subtraction on 'a 'b 'c} ⇒ 'a → 'b → 'c`
Subtraction on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `(..) : int → int → array of int`


----

#### `(/) : forall 'a 'b 'c. {requires division on 'a 'b 'c} ⇒ 'a → 'b → 'c`
Division on `int`, `double`

----

#### `(<) : forall 'a. {requires order on 'a} ⇒ 'a → 'a → bool{#false,#true}`
Ordering on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `(<<) : forall 'a 'b 'c. ('a → 'b) → ('c → 'a) → 'c → 'b`
Function composition. `(f << g) x == f (g x)`

----

#### `(<=) : forall 'a. {requires order on 'a} ⇒ 'a → 'a → bool{#false,#true}`
Ordering on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `(==) : forall 'a. 'a → 'a → bool{#false,#true}`
The equality function works on any value of the same type. Always returns `#false` for functions

----

#### `(>) : forall 'a. {requires order on 'a} ⇒ 'a → 'a → bool{#false,#true}`
Ordering on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `(>=) : forall 'a. {requires order on 'a} ⇒ 'a → 'a → bool{#false,#true}`
Ordering on `int`, `double`, `word16/32/64`, `time` and `timeDiff`

----

#### `(?) : forall 'a. option of 'a → 'a → 'a`
The `?` function unwraps an optional value, if given a default value to fall back on in case the value of the optional is `None`.
  ~~~inferno
  (Some "hello") ? "hi" == "hello"
  None ? "hi" == "hi"
  ~~~

----

#### `(XOR) : forall 'a. {requires bitlike on 'a} ⇒ 'a → 'a → 'a`
Bitwise XOR

----

#### `(|>) : forall 'a 'b. 'a → ('a → 'b) → 'b`
The pipe operator. `x |> f |> g == g (f x)`

----

#### `(||) : forall 'a. {requires bitlike on 'a} ⇒ 'a → 'a → 'a`
Bitwise OR

----



### Module Array

#### `argmax : forall 'a. {requires order on 'a} ⇒ array of 'a → option of int`
The index of the maximum value in an array, or `None` if empty

----

#### `argmin : forall 'a. {requires order on 'a} ⇒ array of 'a → option of int`
The index of the minimum value in an array, or `None` if empty

----

#### `argsort : forall 'a. {requires order on 'a} ⇒ array of 'a → array of int`
Returns the indices that would sort an array

----

#### `average : forall 'a. {requires numeric on 'a} ⇒ array of 'a → option of double`
The average of the values in an array, or `None` if empty

----

#### `cons : forall 'a. 'a → array of 'a → array of 'a`
Array construction. `cons x xs` is the array that has `x` as its first element and array `xs` as the rest of the array. For example, `cons 3 [1, 2] == [3, 1, 2]`

----

#### `drop : forall 'a. int → array of 'a → array of 'a`
`Array.drop n xs` returns `xs` with the first `n` elements removed.
  If `n` is greater than the length of `xs`, returns the empty array.

----

#### `dropWhile : forall 'a. ('a → bool{#false,#true}) → array of 'a → array of 'a`
`Array.dropWhile p xs` drops the longest (possibly empty) prefix of elements of `xs` satisfying the predicate `p` and returns the remainder

----

#### `filter : forall 'a. ('a → bool{#false,#true}) → array of 'a → array of 'a`
`Array.filter p xs` returns an array containing only the elements of `xs`
  that satisfy the predicate `p`

----

#### `findFirstAndLastSome : forall 'a. array of (option of 'a) → option of ('a, 'a)`


----

#### `findFirstSome : forall 'a. array of (option of 'a) → option of 'a`


----

#### `findLastSome : forall 'a. array of (option of 'a) → option of 'a`


----

#### `get : forall 'a. array of 'a → int → 'a`
Array indexing: gets the ith element of an array. Throws a RuntimeError if i is out of bounds.

----

#### `getOpt : forall 'a. array of 'a → int → option of 'a`
Safe array indexing: gets the ith element of an array. Returns None if i is out of bounds.

----

#### `keepSomes : forall 'a. array of (option of 'a) → array of 'a`
`Array.keepSomes` discards any `None` values in an array and unwaps all `Some`s.
  ~~~inferno
  Array.keepSomes [None, Some "hello", None, Some "world"] = ["hello", "world"]
  ~~~

----

#### `length : forall 'a. array of 'a → int`


----

#### `magnitude : forall 'a. {requires numeric on 'a} ⇒ array of 'a → option of double`
Returns the Euclidean norm of an array, or `None` if empty

----

#### `map : forall 'a 'b. ('a → 'b) → array of 'a → array of 'b`
The `Array.map` function takes a function `f` and an array of elements and applies `f` to each one

----

#### `maximum : forall 'a. {requires order on 'a} ⇒ array of 'a → option of 'a`
The maximum value in an array, or `None` if empty

----

#### `median : forall 'a. {requires numeric on 'a} ⇒ array of 'a → option of double`
Return the median of the values in an array, or `None` if empty

----

#### `minimum : forall 'a. {requires order on 'a} ⇒ array of 'a → option of 'a`
The minimum value in an array, or `None` if empty

----

#### `norm : forall 'a. {requires numeric on 'a} ⇒ array of 'a → option of double`
Returns the Euclidean norm of an array, or `None` if empty

----

#### `range : int → int → array of int`
The `Array.range` function takes two `int` arguments `n` and `m` and produces an array `[n,...,m]`.
  If `m` > `n`, the empty array is returned.

----

#### `reduce : forall 'a 'b. ('a → 'b → 'a) → 'a → array of 'b → 'a`
`reduce` applied to a binary operator, a starting value (typically an identity of the operator, e.g. `0`), and an array, reduces the array using the binary operator, from left to right:
  ~~~inferno
  reduce f z [x1, x2, ..., xn] == (...((z `f` x1) `f` x2) `f`...) `f` xn
  ~~~
  Example: `reduce (+) 42 [1, 2, 3, 4] == 52`

----

#### `reduceRight : forall 'a 'b. ('a → 'b → 'b) → 'b → array of 'a → 'b`
`reduceRight`, applied to a binary operator, a starting value (typically an identity of the operator), and a array, reduces the array using the binary operator, from right to left:
  ~~~inferno
  reduceRight f z [x1, x2, ..., xn] == x1 `f` (x2 `f` ... (xn `f` z)...)
  ~~~
  Example: `reduceRight (+) 42 [1, 2, 3, 4] == 52`, but `reduceRight (-) 0 [5, 3] == 2` while `reduceRight (-) 0 [3, 5] == -2`

----

#### `reverse : forall 'a. array of 'a → array of 'a`
`Array.reverse xs` returns the elements of `xs` in reverse order

----

#### `singleton : forall 'a. 'a → array of 'a`
This function can be used to create an array with a single element:
  ~~~inferno
  singleton 2
  ~~~

----

#### `sum : forall 'a 'b. {requires addition on 'b 'a 'b,requires rep on 'b,requires zero on 'b} ⇒ array of 'a → 'b`
`Array.sum` computes the sum of elements in an array. The elements can be of type `int`/`double`/`word`.

----

#### `take : forall 'a. int → array of 'a → array of 'a`
`Array.take n xs` returns the first `n` elements of `xs`.
  If `n` is greater than the length of `xs`, returns `xs`.

----

#### `takeWhile : forall 'a. ('a → bool{#false,#true}) → array of 'a → array of 'a`
`Array.takeWhile`, applied to a predicate `p` and a list `xs`, returns the longest prefix (possibly empty) of `xs` of elements that satisfy `p`

----

#### `uncons : forall 'a. array of 'a → option of ('a, array of 'a)`
Array destruction into head and tail. `uncons xs` is `Some (x, xs1)` if array has at least one element and `xs == cons x xs1`, and is `None` if `xs == []`. For example, `uncons [1, 2, 3] == Some (1, [2, 3])`

----

#### `zero : forall 'a. {requires rep on 'a,requires zero on 'a} ⇒ 'a`


----



### Module Option

#### `flatMap : forall 'a 'b. ('a → option of 'b) → option of 'a → option of 'b`
`Option.flatMap f ma` applies `f` to the value inside `ma` and flattens the result,
  i.e. if `ma` is `Some a`, it returns the `option` result of `f a`, otherwise `None`.

----

#### `join : forall 'a. option of (option of 'a) → option of 'a`
`Option.join` removes the outer "layer" of a nested option. (By definition, `Option.join == Option.reduce id None`).
  ~~~inferno
  Option.join None == None
  Option.join (Some None) == None
  Option.join (Some (Some a)) == Some a
  ~~~

----

#### `map : forall 'a 'b. ('a → 'b) → option of 'a → option of 'b`
`Option.map f ma` applies `f` to the value inside `ma`, namely if `ma` is `Some a`, it will return `Some (f a)`.

----

#### `mergeTuple : forall 'a 'b. (option of 'a, option of 'b) → option of ('a, 'b)`
Given a tuple `(Some x , Some y)`, `Option.mergeTuple` returns `Some (x , y)`. If any of the components are `None` it returns `None`.

----

#### `reduce : forall 'a 'b. ('a → 'b) → 'b → option of 'a → 'b`
`Option.reduce f o d` unwraps an optional value `o` and applies `f` to it, if o contains a `Some` value. Otherwise it returns the default value `d`.
  ~~~inferno
  Option.reduce (fun str -> `${str} there!`) "hi" (Some "hello") == "hello there!"
  Option.reduce (fun str -> `${str} there!`) "hi" None == "hi"
  ~~~

----

#### `singleton : forall 'a. 'a → option of 'a`


----

#### `traverse : forall 'a 'b. ('a → option of 'b) → array of 'a → option of (array of 'b)`
`Option.traverse f xs` applies `f` to each element of `xs`, returning `Some` of
  the resulting array if all applications return `Some`, or `None` if any returns `None`.

----



### Module Text

#### `append : text → text → text`


----

#### `decodeUtf8 : array of word16 → text`
Decode UTF-8 bytes to text. Takes an array of `word16` values
  (each representing a byte, 0-255) and converts them to text. Uses lenient
  decoding to handle invalid UTF-8 sequences gracefully. Note: We use `word16`
  instead of `word8` because Inferno does not currently support `word8`.

----

#### `encodeUtf8 : text → array of word16`
Encode text as UTF-8 bytes. Returns an array of `word16` values representing
  the UTF-8 byte sequence. Each `word16` represents one byte (0-255). Note: We use
  `word16` instead of `word8` because Inferno does not currently support `word8`.

----

#### `length : text → int`


----

#### `splitAt : int → text → (text, text)`


----

#### `strip : text → text`


----

#### `toLower : text → text`
Converts text to lowercase

----

#### `toUpper : text → text`
Converts text to uppercase

----

#### `unwords : array of text → text`
Joins an array of text values into a single text, separating each element
  with a space. Useful for splitting large amounts of text across lines

----



### Module Time

#### `day : time → time`
Rounds down to the start of the nearest day

----

#### `days : int → timeDiff`


----

#### `daysBefore : time → int → time`


----

#### `formatTime : time → text → text`
Format time to string

----

#### `hour : time → time`
Rounds down to the start of the nearest hour

----

#### `hours : int → timeDiff`


----

#### `hoursBefore : time → int → time`


----

#### `intervalEvery : timeDiff → time → time → array of time`


----

#### `minutes : int → timeDiff`


----

#### `minutesBefore : time → int → time`


----

#### `month : time → time`
Rounds down to the start of the nearest month

----

#### `monthsBefore : time → int → time`
Subtracts the given number of months, with days past the last day of the month clipped to the last day. For instance, 1 month before 2005-03-30 is 2005-02-28.

----

#### `parseTime : text → text → option of time`
`parseTime format str` parses the string input `str` into a `time` value
  using the provided `format` string. If `str` cannot be parsed according to
  `format`, then `None` is returned, otherwise `Some time`

  Example: `parseTime "%Y-%m-%d %H:%M:%S" "2025-09-17 07:23:46" == Some (toTime (seconds 1758093826))`

  For available format characters, please see the documentation for
  https://hackage-content.haskell.org/package/time-1.15/docs/Data-Time-Format.html#v:formatTime

----

#### `seconds : int → timeDiff`


----

#### `secondsBefore : time → int → time`


----

#### `timeToInt : time → int`
Convert time to int (returned as number of seconds since January 1, 1970, 00:00, not counting leap seconds)

----

#### `toTime : timeDiff → time`


----

#### `weeks : int → timeDiff`


----

#### `weeksBefore : time → int → time`


----

#### `year : time → time`
Rounds down to the start of the nearest year

----

#### `yearsBefore : time → int → time`
Subtracts the given number of years, with days past the last day of the month clipped to the last day. For instance, 2 years before 2006-02-29 is 2004-02-28.

----



## Type Classes
#### `abs`
- `int`
- `double`
- `timeDiff`

#### `addition`
- `int int int`
- `int double double`
- `double int double`
- `double double double`
- `word16 word16 word16`
- `word16 word32 word32`
- `word16 word64 word64`
- `word32 word16 word32`
- `word32 word32 word32`
- `word32 word64 word64`
- `word64 word16 word64`
- `word64 word32 word64`
- `word64 word64 word64`
- `time timeDiff time`
- `timeDiff time time`
- `timeDiff timeDiff timeDiff`

#### `bitlike`
- `word16`
- `word32`
- `word64`
- `bool{#false,#true}`

#### `division`
- `int int int`
- `int double double`
- `double int double`
- `double double double`

#### `fromWord`
- `word16`
- `word32`
- `word64`
- `bool{#false,#true}`

#### `multiplication`
- `int int int`
- `int double double`
- `int timeDiff timeDiff`
- `double int double`
- `double double double`
- `timeDiff int timeDiff`

#### `negate`
- `int`
- `double`
- `timeDiff`

#### `order`
- `int`
- `double`
- `time`
- `timeDiff`

#### `power`
- `int`
- `double`

#### `roundable`
- `int`
- `double`

#### `scalar`
- `int`
- `double`
- `bool{#false,#true}`

#### `subtraction`
- `int int int`
- `int double double`
- `double int double`
- `double double double`
- `word16 word16 word16`
- `word32 word32 word32`
- `word64 word64 word64`
- `time timeDiff time`
- `timeDiff timeDiff timeDiff`

#### `toWord16`
- `int`
- `word16`
- `word32`
- `word64`
- `bool{#false,#true}`

#### `toWord32`
- `int`
- `word16`
- `word32`
- `word64`
- `bool{#false,#true}`

#### `toWord64`
- `int`
- `word16`
- `word32`
- `word64`
- `bool{#false,#true}`

#### `zero`
- `int`
- `double`
- `word16`
- `word32`
- `word64`
- `timeDiff`


