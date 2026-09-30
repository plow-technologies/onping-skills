
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
Returns the latest value of the parameter (and the corresponding timestamp),
  if one exists.

----

#### `latestValueAndTimeBefore : forall 'a. time → series of 'a → option of ('a, time)`
Returns the latest value of the parameter (and the corresponding timestamp)
  before the given time, if one exists.

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

#### `makeWrites : forall 'a. series of 'a → array of ('a, time) → write`
Create a `write` object encapsulating an array of `(time, 'a)` values to be
  written to a given parameter. All ML scripts must return an array of such `write`
  objects, potentially empty, and this is the only way for them to write values to parameters.

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
  For example, if resolution is 128 (thus chunks are 0-127, 128-255, 256-383, ...),
  and the parameter `p` has values:
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
Returns the value of the parameter in the chunk containing the given time,
  if it exists, or in the closest adjacent chunk (previous or next chunk), if it exists.
  For example, if resolution is 128 (thus chunks are 0-127, 128-255, 256-383, ...),
  and the parameter `p` has values:
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



### Module JSON

#### `asArray : json → option of (array of json)`
`JSON.asArray j` attempts to interpret `j` as a JSON array,
  returning `None` if `j` is not an array

----

#### `asBool : json → option of bool{#false,#true}`
`JSON.asBool j` attempts to interpret `j` as a JSON boolean,
  returning `None` if `j` is not a boolean

----

#### `asNumber : json → option of double`
`JSON.asDouble j` attempts to interpret `j` as a JSON number,
  returning `None` if `j` is not a number

----

#### `asObject : json → option of (array of (text, json))`
`JSON.asObject j` attempts to interpret `j` as a JSON object,
  returning `None` if `j` is not an object

----

#### `asText : json → option of text`
`JSON.asText j` attempts to interpret `j` as a JSON string,
  returning `None` if `j` is not a string

----

#### `atKey : json → text → option of json`
`JSON.atKey j k` looks up the key `k` in the JSON object `j`,
  returning `None` if `j` is not an object or if `k` is not present

----



### Module ML

#### `asArray1 : tensor → array of double`


----

#### `asArray2 : tensor → array of (array of double)`


----

#### `asArray3 : tensor → array of (array of (array of double))`


----

#### `asArray4 : tensor → array of (array of (array of (array of double)))`


----

#### `asDouble : tensor → double`


----

#### `asTensor0 : dtype{#bool,#double,#float,#int} → double → tensor`


----

#### `asTensor1 : dtype{#bool,#double,#float,#int} → array of double → tensor`


----

#### `asTensor2 : dtype{#bool,#double,#float,#int} → array of (array of double) → tensor`


----

#### `asTensor3 : dtype{#bool,#double,#float,#int} → array of (array of (array of double)) → tensor`


----

#### `asTensor4 : dtype{#bool,#double,#float,#int} → array of (array of (array of (array of double))) → tensor`


----

#### `forward : model → array of tensor → array of tensor`
Run a forward pass through a TorchScript model, evaluating the model on
  the provided input tensors and returning the resulting output tensors.

  NOTE: This function only works for TorchScript models. You cannot `forward`
  to Bedrock models

----

#### `loadModel : modelName → model`
Load a named, serialized model (TorchScript) or the configuration of a
  Bedrock-based model. Note that the type of model contained within determines if
  it is compatible with `forward` (TorchScript) or with `prompt` (Bedrock)

----

#### `ones : dtype{#bool,#double,#float,#int} → array of int → tensor`


----

#### `prompt : model → text → text`
Prompt an LLM, i.e Bedrock, model. Raw text is returned: no structure
  is guaranteed beyond a readable string.

  NOTE: This function only works for Bedrock models. You cannot `prompt` a
  TorchScript model

----

#### `promptWith : model → text → schema → json`
Prompt an LLM, i.e Bedrock, model. Structured JSON is returned and
  parseable using `JSON` module functions. If the text cannot be parsed into a
  JSON structure, it becomes JSON text.

  For a contrived example, `promptWith m t s` where
  - `m` is a Bedrock model
  - `t` is the prompt: `"Find any outlier(s) in this set of number [1, 2203, 3, 4, 9861]"`
  - `s` is the schema: `Schema.array (Schema.fromPrimitive Schema.#number)`

  will automatically prompt the LLM to return a JSON response following the
  schema `[$number]`. The output can be parsed using `JSON` and `Option` module
  members. In this case, `Option.flapMap (Option.traverse JSON.asNumber (JSON.asArray ...))`

  See the `Schema` module documentation for available schema structures. Note that
  both primitives and composite types are supported. For example, you can request
  nested objects, arrays of objects, etc...

  NOTE: This function only works for Bedrock models. You cannot `promptWith` a
  TorchScript model.

----

#### `randnIO : dtype{#double,#float,#int} → array of int → tensor`
An impure (pseudo)random tensor generator

----

#### `toDevice : device{#cpu,#cuda} → tensor → tensor`
Move a tensor to a different device

----

#### `toDeviceUnsafe : text → tensor → tensor`
Move a tensor to a different device, e.g. "cpu" or "cuda:0"
  (without checking validity of device name)

----

#### `toType : dtype{#bool,#double,#float,#int} → tensor → tensor`


----

#### `unsafeLoadScript : text → model`


----

#### `zeros : dtype{#bool,#double,#float,#int} → array of int → tensor`


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



### Module Print

#### `print : forall 'a. 'a → ()`
Convert a value to text and print it to the console

----

#### `printWith : forall 'a. text → 'a → ()`
Convert a value to text and print it to the console, with a text prefix

----

#### `show : forall 'a. 'a → text`
Convert a value to text

----



### Module Schema

#### `array : schema → schema`
Turn the `schema` into an array of `schema`. This only takes a _single_
  `schema` argument because Inferno `array`s are homogeneous. For example,
  `Schema.array (Schema.fromPrimitive Schema.#string)` means we are expecting an
  array of strings.

  ~~~inferno
  // We are expecting an array of doubles as a response
  //
  // The response can be consumed with `Option.flatMap (Option.traverse JSON.asNumber) (JSON.asArray ...)`
  Schema.array (Schema.fromPrimitive Schema.#number) == [$number]
  ~~~

----

#### `fromPrimitive : primitive{#bool,#number,#string} → schema`
Turn a `primitive` into a `schema`, this can either be used directly or
  used with `object` or `array` to produce more complex schemas.

  ~~~inferno
  // We are expecting a string as a response
  //
  // The response can then be consumed with `JSON.asString ...`
  Schema.fromPrimitive Schema.#string == "$string"
  ~~~

----

#### `object : array of (text, schema) → schema`
Turn the array of key-value pairs into a `schema`. The individual `schema`s
  under each key do NOT need to be homogeneous: any schema type is supported,
  allowing for e.g. nested objects, arrays, etc...

  ~~~inferno
  // We are expecting an object with a single `ok` boolean key as a response
  //
  // The response can be consumed with `Option.flatMap (JSON.asBool) (JSON.atKey "ok" ...)`
  Schema.object [("ok", Schema.fromPrimitive Schema.#bool)] == {"ok": "$bool"}
  ~~~

----



### Module Tensor

#### `add : tensor → tensor → tensor`
`add t1 t2` adds each element of the tensor `t2` to each element of the
  tensor `t1` and returns a new resulting tensor

----

#### `addScalar : forall 'a. {requires scalar on 'a} ⇒ 'a → tensor → tensor`
`addScalar summand t` adds each element of `t` with the scalar `summand`
  and returns a new resulting tensor

----

#### `all : tensor → bool{#false,#true}`
Returns true if all elements in the tensor are true, false otherwise

----

#### `allDim : int → bool{#false,#true} → tensor → tensor`
`allDim dim keepdim t` returns true if all elements in each row of `t`
  in the given dimension `dim` are true, false otherwise. If `keepdim` is `#true`,
  the output tensor is of the same size as `t` except in the dimension `dim` where
  it is of size 1. Otherwise, `dim` is squeezed, resulting in the output tensor
  having 1 fewer dimension than `t`

----

#### `any : tensor → bool{#false,#true}`
Returns true if any element in the tensor is true, false otherwise

----

#### `anyDim : int → bool{#false,#true} → tensor → tensor`
`anyDim dim keepdim t` returns true if any elements in each row of `t`
  in the given dimension `dim` are true, false otherwise. If `keepdim` is `#true`,
  the output tensor is of the same size as `t` except in the dimension `dim` where
  it is of size 1. Otherwise, `dim` is squeezed, resulting in the output tensor
  having 1 fewer dimension than `t`

----

#### `argmax : int → bool{#false,#true} → tensor → tensor`
`argmax i k t` is the argmax of tensor `t` along dimension `i`.
  `k` denotes whether the output tensor has dim retained or not.

----

#### `bitwiseNot : tensor → tensor`
Computes the bitwise NOT of the given input tensor. The input tensor must
  be of integral or Boolean types. For bool tensors, it computes the logical NOT

----

#### `cat : int → array of tensor → tensor`
`cat dim ts` concatenates `ts` in the given `dim`. All tensors must either
  have the same shape (except in the concatenating dimension) or be empty

----

#### `ceil : tensor → tensor`
Returns a new tensor with the ceil of the elements of input, the smallest
  integer greater than or equal to each element

----

#### `celu : double → tensor → tensor`
`celu α t` Applies element-wise `CELU(x) = max(0, x) + min(0, α * (exp(x/α) - 1))`

----

#### `chainMatmul : array of tensor → tensor`
`chainMatmul ts` returns the matrix product of the NN 2-D tensors `ts`.
  This product is efficiently computed using the matrix chain order algorithm
  which selects the order in which incurs the lowest cost in terms of arithmetic
  operations. Note that since this is a function to compute the product, NN needs
  to be greater than or equal to 2. If equal to 2 then a trivial matrix-matrix
  product is returned. If NN is 1, then this is a no-op - the original matrix is
  returned as is

----

#### `chunk : int → int → tensor → array of tensor`
`chunk chunks dim t` splits a tensor into a specific number of chunks.
  The last chunk will be smaller if the size of `t` along the given dimension
  `dim` is not divisible by `chunks`

----

#### `clamp : double → double → tensor → tensor`
`clamp min max t` clamps all elements in input into the range `[ min, max ]`
  and returns the resulting tensor

----

#### `clampMax : double → tensor → tensor`
`clampMax max t` clamps all elements in `t` to be smaller or equal to `max`

----

#### `clampMin : double → tensor → tensor`
`clampMin min t` clamps all elements in `t` to be larger or equal to `min`

----

#### `device : tensor → device{#cpu,#cuda}`
Returns the device on which the tensor is currently allocated

----

#### `digamma : tensor → tensor`
Computes the logarithmic derivative of the gamma function on input

----

#### `dim : tensor → int`
Returns the dimensions of the input tensor

----

#### `dist : double → tensor → tensor`
`dist p t1 t2` returns the `p`-norm of `(t1 - t2)`. The shapes of `t1`
  and `t2` must be broadcastable

----

#### `div : tensor → tensor → tensor`
`div t1 t2` performs element wise division of tensor `t2` from input tensor
  `t1` and returns a new resulting tensor

----

#### `divScalar : forall 'a. {requires scalar on 'a} ⇒ 'a → tensor → tensor`
`divScalar divisor t` divides each element of `t` with the scalar `divisor`
  and returns a new resulting tensor

----

#### `dquantile : tensor → double → int → bool{#false,#true} → qinterp{#higher,#linear,#lower,#midpoint,#nearest} → tensor`
`dquantile t q dim keepdim interp` computes the `q`-th quantile of the tensor `t`
  along dimension `dim`. If `keepdim` is true, the output tensor has the same number of
  dimensions as `t`, with the reduced dimension of size 1. The interpolation method is
  specified by `interp`. This variant takes a `double` for the quantile value instead of a `tensor`.

  NOTE: The `q` quantile value MUST be in the range 0-1!

----

#### `dtype : tensor → dtype{#bool,#double,#float,#int}`
Returns the data type of the input tensor

----

#### `elu : forall 'a. {requires scalar on 'a} ⇒ 'a → tensor → tensor`
`elu α t` applies exponential linear unit function element-wise,
  with alpha input `α`, `ELU(x) = max(0, x) + min(0, α * (x^2 - 1))`

----

#### `eq : tensor → tensor → tensor`
`eq t1 t2` computes `t1 == t2` element-wise

----

#### `erf : tensor → tensor`
Computes the error function of each element

----

#### `erfc : tensor → tensor`
Computes the complementary error function of each element

----

#### `erfinv : tensor → tensor`
Computes the inverse error function of each element of input.
  The inverse error function is defined in the range `(-1, 1)(−1,1)` as:
  `erfinv(erf(x)) = x`

----

#### `flatten : int → int → tensor → tensor`
`flatten startdim enddim t` flattens `t` by reshaping it into a
  one-dimensional tensor. Only dimensions starting with `startdim` and ending
  with `enddim` are flattened. The order of elements in `t` is unchanged

----

#### `flattenAll : tensor → tensor`
`flatten t` flattens `t` by reshaping it into a one-dimensional tensor

----

#### `frac : tensor → tensor`
Computes the fractional portion of each element in input.
  `output = input - (floor . abs) input * (sign input)`

----

#### `ge : tensor → tensor → tensor`
`ge t1 t2` computes `t1 ≥ t2` element-wise

----

#### `gelu : tensor → tensor`
Applies element-wise the function `GELU(x) = x * φ(x)` where `φ(x)` is
  the Cumulative Distribution Function for Gaussian Distribution

----

#### `glu : int → tensor → tensor`
`glu dim t` is the gated linear unit. Computes: `GLU(a, b) = a ⊗ Σ(b)`,
  where `t` is split in half along `dim` to form `a` and `b`, `Σ` is the sigmoid
  function and `⊗` is the element-wise product between matrices

----

#### `gt : tensor → tensor → tensor`
`gt t1 t2` computes `t1 > t2` element-wise

----

#### `index : array of tensor → tensor → tensor`


----

#### `indexCopy : int → tensor → tensor → tensor → tensor`
`indexCopy dim index source t` copies the elements of `source` into `t`
  (out-of-place) by selecting the indices in the order given in the `index`
  tensor. For example, if `dim == 0` and `index[i] == j`, then the `i`th row of
  `source` is copied to the `j`th row of `t`. The `dim`th dimension of `source`
  must have the same size as the length of `index` (which must be a vector),
  and all other dimensions must match `t`, or an error will be raised

----

#### `indexPut : bool{#false,#true} → array of tensor → tensor → tensor → tensor`
`indexPut accumulate indices source t` Puts values from the tensor `source`
  into `t` (out-of-place) using the indices specified in `indices` (which is a
  tuple of tensors). The expression `Tensor.indexPut #true indices source t` is
  equivalent to `t[indices] = source`. If `accumulate` is true, the elements in
  `source` are added to `t`. If accumulate is false, the behavior is undefined if
  indices contain duplicate elements

----

#### `inverse : tensor → tensor`
Takes the inverse of the square matrix input. The input can be batches of
  2D square tensors, in which case this function would return a tensor composed
  of individual inverses

----

#### `isNonzero : tensor → bool{#false,#true}`
Returns true if the input is a single element tensor which is not equal
  to zero after type conversions

----

#### `isSameSize : tensor → tensor → bool{#false,#true}`


----

#### `isSigned : tensor → bool{#false,#true}`
Returns true if the data type of the input is a signed type

----

#### `isnan : tensor → tensor`
Returns a new tensor with dtype `#bool` whose elements represent if each
  element of the input is NaN or not. Complex values are considered NaN when either
  their real and/or imaginary part is NaN

----

#### `le : tensor → tensor → tensor`
`le t1 t2` computes `t1 ≤ t2` element-wise

----

#### `lgamma : tensor → tensor`
Computes the logarithm of the gamma function on input

----

#### `log10 : tensor → tensor`
Returns a new tensor with the logarithm to the base 10 of the elements of input

----

#### `log1p : tensor → tensor`
`log1p t` returns a new tensor with the natural logarithm of `(1 + t)`

----

#### `log2 : tensor → tensor`
Returns a new tensor with the logarithm to the base 2 of the elements of input

----

#### `logSoftmax : int → tensor → tensor`
`logSoftmax dim t` applies a softmax followed by a logarithm. While mathematically
  equivalent to `log(softmax(t))`, doing these two operations separately is slower, and
  numerically unstable. This function uses an alternative formulation to compute the output
  and gradient correctly

----

#### `logicalAnd : tensor → tensor → tensor`
Computes the element-wise logical AND of the given input tensors.
  Zeros are treated as false and nonzeros are treated as true

----

#### `logicalNot : tensor → tensor`
Computes the element-wise logical NOT of the given input tensor. The output
  tensor will have the `#bool` dtype. If the input tensor is not a bool tensor,
  zeros are treated as false and non-zeros are treated as true

----

#### `logicalOr : tensor → tensor → tensor`
Computes the element-wise logical OR of the given input tensors.
  Zeros are treated as false and nonzeros are treated as true

----

#### `logicalXor : tensor → tensor → tensor`
Computes the element-wise logical XOR of the given input tensors.
  Zeros are treated as false and nonzeros are treated as true

----

#### `lt : tensor → tensor → tensor`
`lt t1 t2` computes `t1 < t2` element-wise

----

#### `maskedSelect : tensor → tensor → tensor`
`maskedSelect mask t` returns a new 1-D tensor which indexes the input
  tensor according to the boolean mask `mask` which is a tensor with dtype `#bool`.
  The shapes of the mask tensor and the input tensor don’t need to match, but they
  must be broadcastable

----

#### `matmul : tensor → tensor → tensor`
`matmul t1 t2` is the matrix product of two tensors. The behavior depends
  on the dimensionality of the tensors as follows:
    - If both tensors are 1-dimensional, the dot product (scalar) is returned
    - If both arguments are 2-dimensional, the matrix-matrix product is returned
    - If `t1` is 1-dimensional and `t2` is 2-dimensional, a 1 is prepended to
      its dimension for the purpose of the matrix multiply. After the matrix
      multiply, the prepended dimension is removed
    - If `t1` is 2-dimensional and the `t2` is 1-dimensional, the matrix-vector product is returned
    - If both arguments are at least 1-dimensional and at least one argument is
      N-dimensional (where N > 2), then a batched matrix multiply is returned

----

#### `mean : tensor → tensor`
Returns the mean value of all elements in the input tensor

----

#### `median : tensor → tensor`
Returns the median value of all elements in the input tensor

----

#### `mseLoss : tensor → tensor → tensor`
`mseLoss target t` creates a criterion that measures the mean squared error
  (squared L2 norm) between each element in the input `t` and `target`

----

#### `mul : tensor → tensor → tensor`
`mul t1 t2` multiplies each element of the tensor `t2` to each element of the
  input tensor `t1` and returns a new resulting tensor

----

#### `mulScalar : forall 'a. {requires scalar on 'a} ⇒ 'a → tensor → tensor`
`mulScalar multiplier t` multiplies each element of `t` with the scalar
  `multiplier` and returns a new resulting tensor

----

#### `mvlgamma : int → tensor → tensor`
`mvlgamma p t` computes the multivariate log-gamma function with dimension
  `p` element-wise. All elements must be greater than `(p-1)/2`, otherwise an
  error would be thrown

----

#### `ne : tensor → tensor → tensor`
`ne t1 t2` computes `t1 ≠ t2` element-wise

----

#### `nonzero : tensor → tensor`
Returns a tensor containing the indices of all non-zero elements of input.
  Each row in the result contains the indices of a non-zero element in input.
  The result is sorted lexicographically, with the last index changing the fastest

----

#### `numel : tensor → int`
Returns the total number of elements in the input tensor

----

#### `oneHot : int → tensor → tensor`
`oneHot i t` is one hot encoding of the given input `t`. The encoding is
  based on the given number of classes `i`

----

#### `permute : array of int → tensor → tensor`
`permute dims t` permutes the dimensions of this tensor, where `dims`
  corresponds to the ordering of dimensions to permute with

----

#### `polygamma : int → tensor → tensor`
`polygamma n t` computes the `n`th derivative of the digamma function on
  input. n≥0n≥0 is called the order of the polygamma function

----

#### `pow : forall 'a. {requires scalar on 'a} ⇒ 'a → tensor → tensor`
`pow e t` takes the power of each element in `t` with exponent `e` and
  returns a tensor with the result

----

#### `powt : tensor → tensor → tensor`
`powt t1 t2` takes the power of each element in input `t1` with exponent
  `t2` and returns a tensor with the result. Exponent `t2` is a tensor with the
  same number of elements as the input

----

#### `quantile : tensor → tensor → int → bool{#false,#true} → qinterp{#higher,#linear,#lower,#midpoint,#nearest} → tensor`
`quantile t q dim keepdim interp` computes the `q`-th quantile of the tensor `t`
  along dimension `dim`. If `keepdim` is true, the output tensor has the same number of
  dimensions as `t`, with the reduced dimension of size 1. The interpolation method is
  specified by `interp`

----

#### `relu : tensor → tensor`
Applies the rectified linear unit function element-wise

----

#### `repeat : array of int → tensor → tensor`
`repeat times t` repeats `t` according to the number of `times` to repeat
  `t` along each dimension

----

#### `roll : tensor → int → int → tensor`
`roll t shift dim` rolls the tensor `t` along the given dimension `dim`.
  Elements that are shifted beyond the last position are re-introduced at the first
  position. `shift` specifies the number of places by which the elements of the
  tensor are shifted

----

#### `selu : tensor → tensor`
Applies element-wise, `SELU(x) = scale * (max(0, x) + min(0, α * (exp(x) - 1)))`,
  with `α`=1.6732632423543772848170429916717 and `scale`=1.0507009873554804934193349852946

----

#### `shape : tensor → array of int`
Returns the shape of the tensor

----

#### `sigmoid : tensor → tensor`
Applies element-wise sigmoid function

----

#### `sign : tensor → tensor`
Returns a new tensor with the signs of the elements of the input

----

#### `size : int → tensor → int`
`size dim t` returns the size of the given `dim` of the input `t`

----

#### `softShrink : double → tensor → tensor`
`softShrink lambda t` applies the soft shrinkage function elementwise

----

#### `softmax : int → tensor → tensor`
`softmax dim t` applies a softmax function. It is applied to all slices along `dim`,
  and will re-scale them so that the elements lie in the range `[0, 1]` and sum to 1

----

#### `solve : tensor → tensor → tensor`
`solve t square` returns the solution to the system of linear equations
  represented by `AX = BAX=B` and the LU factorization of A

----

#### `split : int → int → tensor → array of tensor`
`split size dim t` splits `t` into chunks of given `size` if possible

----

#### `squeezeAll : tensor → tensor`
Returns a tensor with all specified dimensions of the input of size 1
  removed. For example, if the input `t` is of shape: `(A×1×B×C×1×D)` then
  `squeezeAll t` will be of shape: `(A×B×C×D)`

----

#### `squeezeDim : int → tensor → tensor`
Similar to `Tensor.squeezeAll`, but only squeezes along the provided dim.
  For example, if input `t` is of shape: `(A×1×B)`, `squeeze t 0` leaves the tensor
  unchanged, but `squeeze t 1` will squeeze the tensor to the shape `(A×B)`

----

#### `stack : int → array of tensor → tensor`
`stack i ts` takes an array of tensors `ts` and appends them along the
  dimension `i` in a new tensor. All tensors need to be of the same size

----

#### `std : tensor → tensor`
Returns the standard deviation of all elements in the input tensor

----

#### `sub : tensor → tensor → tensor`
`sub t1 t2` performs element wise subtraction of tensor `t2` from input tensor
  `t1` and returns a new resulting tensor

----

#### `subScalar : forall 'a. {requires scalar on 'a} ⇒ 'a → tensor → tensor`
`subScalar subtrahend t` subtracts each element of `t` with the scalar
  `subtrahend` and returns a new resulting tensor

----

#### `sumAll : tensor → tensor`
Returns the sum of all elements in the input tensor

----

#### `take : tensor → tensor → tensor`
`take indices t` returns a new tensor with the elements of input at the
  given `indices`. The input tensor is treated as if it were viewed as a 1-D tensor.
  The result takes the same shape as the indices

----

#### `threshold : double → double → tensor → tensor`
`threshold d value t` thresholds each element of the input according to `d`

----

#### `transpose : int → int → tensor → tensor`
`transpose dim1 dim2 t` returns a tensor that is a transposed version of `t`.
  The given dimensions `dim1` and `dim2` are swapped

----

#### `transpose2D : tensor → tensor`
Special case of `Tensor.transpose` for a 2D tensor (where `dim1 = 0` and
  `dim2 = 1`)

----

#### `unsqueeze : int → tensor → tensor`
`unsqueeze dim t` returns a new tensor with a dimension of size one
  inserted at the specified position. The returned tensor shares the same
  underlying data with `t`. A `dim` value within the range `[(dim t) - 1, (dim t) + 1)]`
  can be used. Negative `dim` will correspond to unsqueeze applied at
  `dim = dim + (dim t) + 1`

----

#### `var : tensor → tensor`
Returns the variance of all elements in the input tensor

----

#### `view : array of int → tensor → tensor`
`view size t` returns a new tensor with the same data as the `t` but of a
  different shape according to desired `size`

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


