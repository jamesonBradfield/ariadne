#[test]
fn test_new() {
    let entity = Entity::new();
    assert_eq!(entity.health, 100.0);
    assert_eq!(entity.armor, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_heal() {
    let mut entity = Entity::new();
    entity.heal(50.0);
    assert_eq!(entity.health, 100.0);
}

#[test]
fn test_heal_small() {
    let mut entity = Entity::new();
    entity.heal(20.0);
    assert_eq!(entity.health, 100.0);
}

#[test]
fn test_take_damage_less_than_armor() {
    let mut entity = Entity::new();
    entity.take_damage(30.0);
    assert_eq!(entity.health, 100.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage_equal_to_armor() {
    let mut entity = Entity::new();
    entity.take_damage(50.0);
    assert_eq!(entity.health, 100.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage_more_than_armor() {
    let mut entity = Entity::new();
    entity.take_damage(150.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_take_damage_partial() {
    let mut entity = Entity::new();
    entity.take_damage(100.0);
    assert_eq!(