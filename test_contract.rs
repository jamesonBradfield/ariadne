#[test]
fn test_new() {
    let entity = Entity::new();
    assert_eq!(entity.health, 100.0);
    assert_eq!(entity.armor, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage() {
    let mut entity = Entity::new();
    entity.take_damage(30.0);
    assert_eq!(entity.health, 70.0);
    assert!(!entity.is_dead);
    
    entity.take_damage(80.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
    
    entity.take_damage(10.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_heal() {
    let mut entity = Entity::new();
    entity.take_damage(60.0);
    entity.heal(20.0);
    assert_eq!(entity.health, 100.0);
    
    entity.take_damage(150.0);
    entity.heal(50.0);
    assert_eq!(entity.health, 100.0);
}